"""Stand-in adapter: bundled data/cases/*.json -> CaseRecord, for developing agents downstream
of Summarize before the History and Summarize agents exist.

It replaces those agents only roughly: lab findings come from data/labs.py flags (all
`follow_up`), radiology findings are omitted, and risk flags use a tiny table. It never reads
`answer_key`. Swap in the real Summarize output once it lands.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from carerelay.schemas import CaseRecord, CodedItem, Finding, HistoryProfile
from carerelay.service import find_data_dir

ROOT = find_data_dir().parent
CASES_DIR = ROOT / "data" / "cases"
TODAY = date(2026, 10, 23)  # data/README.md: use 2026-10-23 as "today"

# Prototype risk-flag table (ARCHITECTURE.md: History owns the real one).
ICD_FLAGS = {"N18": "ckd", "K70": "liver", "K72": "liver", "K74": "liver", "K76": "liver",
             "Z33": "pregnancy", "E10": "diabetes", "E11": "diabetes",
             "I10": "hypertension", "I11": "hypertension", "I12": "hypertension", "I13": "hypertension"}
ANTICOAGULANTS = ("apixaban", "warfarin", "rivaroxaban", "dabigatran", "edoxaban", "enoxaparin", "heparin")


def _labs_module():
    if str(ROOT / "data") not in sys.path:
        sys.path.insert(0, str(ROOT / "data"))
    import labs  # data/labs.py

    return labs


def _age(birth: str) -> int:
    b = date.fromisoformat(birth)
    return TODAY.year - b.year - ((TODAY.month, TODAY.day) < (b.month, b.day))


def _visit_reason(report: dict) -> str | None:
    for s in report.get("_sections", []):
        if s.get("title", "").upper() in ("CLINICAL INDICATION", "INDICATION", "CLINICAL HISTORY"):
            return s.get("text")
    return None


def history_profile(h: dict) -> HistoryProfile:
    conditions = [CodedItem(system="icd10cm", code=c.get("icd10"), display=c["display"],
                            status=c.get("status"), detail=c.get("onset")) for c in h.get("conditions", [])]
    meds = [CodedItem(system="rxnorm", code=m.get("rxnorm"), display=m["display"],
                      status=m.get("status", "active"), detail=m.get("dosage")) for m in h.get("medications", [])]
    allergies = [CodedItem(system="rxnorm" if a.get("rxnorm") else "text", code=a.get("rxnorm"),
                           display=a["substance"], detail=f"{a.get('reaction', '')}; criticality {a.get('criticality')}")
                 for a in h.get("allergies", [])]
    procedures = [CodedItem(display=p["display"], detail=p.get("date")) for p in h.get("procedures", [])]
    flags = {f for c in conditions if c.code for prefix, f in ICD_FLAGS.items() if c.code.startswith(prefix)}
    if any(a in m.display.lower() for m in meds for a in ANTICOAGULANTS):
        flags.add("anticoagulant")
    specialists = [t["role"].lower() for t in h.get("care_team", [])]
    source = "pdf" if h.get("source") == "pcp_record" else "intake_text"
    return HistoryProfile(conditions=conditions, medications=meds, allergies=allergies, procedures=procedures,
                          known_specialists=specialists, risk_flags=sorted(flags), source=source)


def load_case(case_id: str) -> CaseRecord:
    c = json.loads((CASES_DIR / f"{case_id}.json").read_text())
    labs = _labs_module()
    sex = c["Patient"]["gender"]
    findings = []
    for order in c.get("labs", []):
        for panel in order["panels"]:
            for r in labs.expand_panel(panel, sex)["rows"]:
                if r["flag"]:
                    findings.append(Finding(
                        id=f"lab-{order['accession']}-{r['test']}", source="lab", label=r["test"],
                        value=f"{r['value']} {r['unit']}".strip(), evidence=f"{order['accession']} {panel['panel']}",
                        confidence=1.0, severity="follow_up", incidental=True))
    return CaseRecord(findings=findings, history=history_profile(c["history"]),
                      visit_reason=_visit_reason(c["DiagnosticReport"]), patient_age=_age(c["Patient"]["birthDate"]))


def case_ids() -> list[str]:
    return sorted(p.stem for p in CASES_DIR.glob("case_*.json"))
