"""Run the History Agent (offline) over all 10 bundled cases and score it against the case files.

Ground truth is the ``history`` block of ``data/cases/case_*.json`` (same content as the
``History`` resources in ``data/output/<case>/intake_expected.json``, before FHIR shaping).
PCP summaries must parse exactly (codes are printed). Questionnaires are free text, so offline
we only check that every item was captured as text; coding is covered by scripts/eval_history.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from carerelay.history import build_history_profile
from carerelay.history.parsers.pdf import detect_kind, extract_layout_text, parse_history_pdf
from carerelay.history.risk_flags import explained_by

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "data" / "cases").glob("case_*.json"))
pytestmark = pytest.mark.skipif(not CASES, reason="bundled cases not present")


def _case(path: Path) -> dict:
    return json.loads(path.read_text())


def _pdf(case: dict) -> Path:
    return ROOT / "data" / "output" / case["case_id"] / "history.pdf"


def _ingredient(display: str) -> str:
    return re.split(r"[\s/,(-]", display.strip())[0].lower()


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_kind_detected(path):
    case = _case(path)
    kind = detect_kind(extract_layout_text(_pdf(case)))
    assert kind == case["history"]["source"]


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_patient_header(path):
    case = _case(path)
    profile = parse_history_pdf(_pdf(case), offline=True)
    assert profile.source == "pdf"
    assert profile.document_kind == case["history"]["source"]
    assert profile.patient.gender == case["Patient"]["gender"]
    assert profile.patient.birth_date == case["Patient"]["birthDate"]
    mrn = next(i["value"] for i in case["Patient"]["identifier"] if i["type"]["text"] == "MRN")
    assert profile.patient.patient_id == mrn


@pytest.mark.parametrize("path", [p for p in CASES if _case(p)["history"]["source"] == "pcp_record"], ids=lambda p: p.stem)
def test_pcp_record_parses_exactly(path):
    case = _case(path)
    h = case["history"]
    profile = parse_history_pdf(_pdf(case), offline=True)

    # Conditions: every printed ICD-10 code read, with status and display
    got = {c.code: c for c in profile.conditions}
    assert set(got) == {c["icd10"] for c in h["conditions"]}
    for c in h["conditions"]:
        item = got[c["icd10"]]
        assert item.system == "icd10cm" and item.code_source == "document"
        assert item.status == c["status"]
        assert item.display.lower() == c["display"].lower()
        if c.get("note"):
            assert c["note"][:25] in (item.detail or "")

    # Medications: one row per printed medication, directions captured
    assert [m.display for m in profile.medications] == [m["display"] for m in h["medications"]]
    for exp, got_m in zip(h["medications"], profile.medications):
        assert exp["dosage"][:20] in (got_m.detail or "")

    # Allergies, procedures, family, care team
    assert [a.display.lower() for a in profile.allergies] == [a["substance"].lower() for a in h["allergies"]]
    for exp, got_a in zip(h["allergies"], profile.allergies):
        assert exp["reaction"].lower() in (got_a.detail or "").lower()
        assert f"criticality: {exp['criticality']}" in (got_a.detail or "")
    assert profile.no_known_allergies == bool(h.get("no_known_allergies"))
    assert [p.display for p in profile.procedures] == [p["display"] for p in h["procedures"]]
    assert [f.display for f in profile.family_history] == [f["condition"] for f in h["family_history"]]
    for k, v in h["social_history"].items():
        assert profile.social_history.get(k) == v
    for m in h["care_team"]:
        assert any(m["name"] in entry for entry in profile.care_team), m
    if any(m["role"] == "Primary care" for m in h["care_team"]):
        assert "primary_care" in profile.known_specialists
    if any(m["role"] == "Cardiology" for m in h["care_team"]):
        assert "cardiology" in profile.known_specialists
    assert not any("uncoded" in w and "condition" in w for w in profile.warnings)


@pytest.mark.parametrize(
    "path", [p for p in CASES if _case(p)["history"]["source"] == "patient_questionnaire"], ids=lambda p: p.stem
)
def test_questionnaire_captures_every_item_as_text(path):
    case = _case(path)
    h = case["history"]
    profile = parse_history_pdf(_pdf(case), offline=True)
    assert [c.display for c in profile.conditions] == [c["as_written"] for c in h["conditions"]]
    assert [m.display for m in profile.medications] == [m["as_written"] for m in h["medications"]]
    assert all(c.code is None for c in profile.conditions + profile.medications), "offline must not invent codes"
    if h["allergies"]:
        for exp, got in zip(h["allergies"], profile.allergies):
            assert got.display.lower() in exp["as_written"].lower()
            assert got.detail and exp["reaction"].split()[0].lower() in got.detail.lower()
    else:
        assert profile.no_known_allergies and not profile.allergies
    assert [p.display for p in profile.procedures] == [p["as_written"] for p in h["procedures"]]
    assert [f.display for f in profile.family_history] == [f["as_written"] for f in h["family_history"]]
    assert profile.social_history.get("Tobacco") == h["social_history"]["Tobacco"]
    assert not profile.care_team and not profile.known_specialists
    assert h.get("notes", "")[:30] in profile.social_history.get("Patient notes", "")
    assert any("patient-reported" in w for w in profile.warnings)


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_history_never_explains_incidental_radiology_findings(path):
    """Mirror of data/tests/test_history.py on our side: a parsed history must not turn an incidental
    radiology finding into an expected one via ``explained_by``."""
    case = _case(path)
    profile = parse_history_pdf(_pdf(case), offline=True)
    for item in case["answer_key"]:
        if item["source"] == "radiology" and item["incidental"]:
            assert explained_by(item["finding"], profile) == [], (item["finding"], profile.risk_flags)


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_build_merges_pdf_with_intake_answers(path):
    case = _case(path)
    intake = case["intake"]
    text = "Medications: " + ", ".join(intake.get("medications", []))
    profile = build_history_profile(history_pdf=_pdf(case), intake_text=text, offline=True)
    assert profile.source == "pdf"
    for med in intake.get("medications", []):
        assert any(_ingredient(med) == _ingredient(m.display) or _ingredient(med) in m.display.lower() for m in profile.medications), med
