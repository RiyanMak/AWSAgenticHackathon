"""Score the Lab and Radiology agents against the bundled ground truth.

- Lab rows and flags vs data/output/<case>/intake_expected.json (exact).
- Radiology recall vs the answer_key in data/cases/<case>.json (read here only, never given to agents),
  including the FINDINGS-only safety-net items, plus a false-alarm count on the negative control.

    python -m carerelay.eval [--aws]
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
_FLAG = {"High": "H", "Low": "L", "Abnormal": "A"}
_STOP = {"mild", "moderate", "small", "on", "radiograph", "suggesting", "no", "of", "and", "with", "without", "the",
         "a", "in", "not", "mm", "cm", "chronic", "probable", "simple", "indeterminate", "change", "changes"}


def expected_lab_rows(case_id: str) -> list[tuple]:
    reports = json.loads((ROOT / "output" / case_id / "intake_expected.json").read_text())["LabReports"]
    rows = []
    for r in reports:
        for o in r["result"]:
            v = o["valueQuantity"]["value"] if "valueQuantity" in o else o["valueString"]
            flag = _FLAG.get((o.get("interpretation") or [{}])[0].get("text"), "")
            rows.append((o["code"]["text"], str(v), flag))
    return rows


def _same_value(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip().lower() == b.strip().lower()


def lab_score(case_id: str, lab) -> tuple[int, int]:
    from carerelay.agents.lab import FLAG_LETTER
    got = [(r.analyte, r.value_text, FLAG_LETTER[r.flag]) for r in lab.rows]
    expected = expected_lab_rows(case_id)
    hits = sum(any(g[0] == e[0] and _same_value(g[1], e[1]) and g[2] == e[2] for g in got) for e in expected)
    return hits, len(expected)


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w.rstrip("s") for w in words if w not in _STOP and len(w) > 2}


def matches(item: dict, finding) -> bool:
    want = _terms(item["finding"])
    have = _terms(f"{finding.label} {finding.site or ''}")
    if not want or len(want & have) / len(want) < 0.5:
        return False
    size = item.get("size_mm")
    return not (size and finding.size_mm and abs(size - finding.size_mm) > 1)


def main(results: dict | None = None) -> None:
    """results: optional {case_id: (lab, rad)} from an earlier run, to re-score without calling Bedrock."""
    from carerelay.run_case import run_case

    totals = {"lab": [0, 0], "rad": [0, 0], "findings_only": [0, 0]}
    for path in sorted((ROOT / "cases").glob("case_*.json")):
        case = json.loads(path.read_text())
        cid = case["case_id"]
        lab, rad = results[cid] if results else run_case(cid)
        lh, lt = lab_score(cid, lab)
        # incidental items feed the ledger; "answers the indication" items are often negatives ("No PE"),
        # which the agent deliberately does not list as findings
        key = [a for a in case["answer_key"] if a["source"] == "radiology" and a["incidental"]]
        missed = [a["finding"] for a in key if not any(matches(a, f) for f in rad.findings)]
        fo = [a for a in key if a.get("in_impression") is False]
        fo_hit = sum(any(matches(a, f) for f in rad.findings) for a in fo)
        extra = sum(not any(matches(a, f) for a in key) and not f.answers_indication for f in rad.findings)
        for k, (h, t) in {"lab": (lh, lt), "rad": (len(key) - len(missed), len(key)),
                          "findings_only": (fo_hit, len(fo))}.items():
            totals[k][0] += h
            totals[k][1] += t
        print(f"{cid}  lab rows {lh}/{lt}  incidental recall {len(key) - len(missed)}/{len(key)}"
              f"  findings-only {fo_hit}/{len(fo)}  other findings {extra}  [{rad.extraction_method}]")
        for m in missed:
            print(f"    missed: {m}")
    print("\nTOTAL  " + "  ".join(f"{k} {h}/{t}" for k, (h, t) in totals.items()))


if __name__ == "__main__":
    if "--aws" in sys.argv:
        os.environ["CARERELAY_USE_AWS"] = "1"
    main()
