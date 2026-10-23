"""Lab catalog lookups: reference ranges, H/L/A flags, and FHIR-shaped output.

Case files list lab values only ({"Sodium": 131}); units, ranges, and flags come
from reference/lab_catalog.json so they stay consistent across cases.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "reference" / "lab_catalog.json"
FLAG_TEXT = {"H": "High", "L": "Low", "A": "Abnormal"}


@cache
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def facility(key: str) -> dict:
    return catalog()["facilities"][key]


def test_spec(test: str, sex: str) -> dict:
    spec = dict(catalog()["tests"][test])
    spec.update(spec.pop("by_sex", {}).get(sex, {}))
    return spec


def _numeric(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).lstrip("<>"))
    except ValueError:
        return None


def flag(value, spec: dict) -> str:
    if "low" in spec or "high" in spec:
        v = _numeric(value)
        if v is None:
            raise ValueError(f"Non-numeric value {value!r} for numeric test")
        if "low" in spec and v < spec["low"] and not str(value).startswith(">"):
            return "L"
        if "high" in spec and v > spec["high"] and not str(value).startswith("<"):
            return "H"
        return ""
    return "" if value in spec.get("normal", [spec["ref"]]) else "A"


def expand_panel(panel: dict, sex: str) -> dict:
    """{"panel": name, "values": {...}} -> rows with unit, ref, and flag."""
    expected = catalog()["panels"][panel["panel"]]
    given = panel["values"]
    if set(given) != set(expected):
        raise ValueError(
            f"{panel['panel']}: missing {sorted(set(expected) - set(given))}, "
            f"unexpected {sorted(set(given) - set(expected))}"
        )
    rows = []
    for test in expected:
        spec = test_spec(test, sex)
        value = given[test]
        rows.append(
            {
                "test": test,
                "value": value,
                "unit": spec.get("unit", ""),
                "ref": spec["ref"],
                "low": spec.get("low"),
                "high": spec.get("high"),
                "flag": flag(value, spec),
            }
        )
    return {"panel": panel["panel"], "rows": rows}


def to_fhir(order: dict, sex: str) -> list[dict]:
    """One FHIR-shaped DiagnosticReport per panel, with Observations inline."""
    lab = facility(order["lab"])
    reports = []
    for panel in order["panels"]:
        expanded = expand_panel(panel, sex)
        observations = []
        for r in expanded["rows"]:
            obs = {
                "resourceType": "Observation",
                "status": "final",
                "category": [{"text": "laboratory"}],
                "code": {"text": r["test"]},
                "effectiveDateTime": order["collected"],
            }
            num = isinstance(r["value"], (int, float))
            obs["valueQuantity" if num else "valueString"] = (
                {"value": r["value"], "unit": r["unit"]} if num else str(r["value"])
            )
            rr = {"text": r["ref"]}
            if r["low"] is not None:
                rr["low"] = {"value": r["low"], "unit": r["unit"]}
            if r["high"] is not None:
                rr["high"] = {"value": r["high"], "unit": r["unit"]}
            obs["referenceRange"] = [rr]
            if r["flag"]:
                obs["interpretation"] = [{"text": FLAG_TEXT[r["flag"]]}]
            observations.append(obs)
        reports.append(
            {
                "resourceType": "DiagnosticReport",
                "identifier": [{"type": {"text": "Accession"}, "value": order["accession"]}],
                "status": "final",
                "category": [{"text": "Laboratory"}],
                "code": {"text": panel["panel"]},
                "effectiveDateTime": order["collected"],
                "issued": order["reported"],
                "basedOn": [{"display": order["ordering"]}],
                "performer": [{"display": lab["name"]}],
                "result": observations,
            }
        )
    return reports
