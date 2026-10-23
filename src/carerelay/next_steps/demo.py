"""Run Next Steps on a bundled case, with the answer key's finding/triage standing in for Summarize.

DEVELOPMENT AND EVAL ONLY. Summarize is owned by another teammate and does not exist yet, so this feeds Next
Steps the finding label, source, triage and incidental flag from data/cases/<case>.json. It never passes the
answer key's follow-up services; choosing those is Next Steps' job, and eval compares against them.

    python -m carerelay.next_steps.demo case_001 [--llm] [--json]
"""

from __future__ import annotations

import json
import sys
from typing import Any

from carerelay.service import find_data_dir

from .context import patient_context
from .schema import NextStepsRequest, RoutedFinding


def load_case(case_id: str) -> dict[str, Any]:
    return json.loads((find_data_dir() / "cases" / f"{case_id}.json").read_text())


def request_from_case(case: dict[str, Any]) -> NextStepsRequest:
    findings = [
        RoutedFinding(id=f"{a['source'][:3]}-{i + 1}", source=a["source"], label=a["finding"], triage=a["triage"],
                      incidental=a["incidental"], site=a.get("site"), size_mm=a.get("size_mm"))
        for i, a in enumerate(case["answer_key"])
    ]
    care_team = [f"{m['name']}, {m['organization']}" for m in case["history"].get("care_team", []) if m.get("name")]
    return NextStepsRequest(findings=findings, coverage=case["Coverage"],
                            patient=patient_context(case["intake"], case["Patient"], care_team))


def _print(plan) -> None:
    print(f"COVERAGE: {plan.coverage.summary}")
    for s in plan.steps:
        where = f"{s.provider_name} ({s.distance_miles} mi{'' if s.in_network else ', OUT OF NETWORK'})" \
            if s.provider_id else ""
        when = s.slot_start.replace("T", " ") if s.slot_start else ""
        cost = f"${s.patient_pays:,.2f}" if s.patient_pays is not None else ""
        print(f"  {s.status:16} {s.triage:6} {s.service:22} {when:17} {cost:>10}  {where}")
        for n in s.notes:
            print(f"{'':26}- {n}")
    for n in plan.no_action:
        print(f"  no action        {n.label}: {n.reason}")
    print(f"TOTAL ${plan.total_patient_pays:,.2f}  [{plan.method}]")
    print(f"SUMMARY: {plan.summary}")
    for n in plan.caregiver_notes + plan.notes:
        print(f"  note: {n}")


if __name__ == "__main__":
    from .agent import run_next_steps

    case_id = next((a for a in sys.argv[1:] if not a.startswith("--")), "case_001")
    result = run_next_steps(request_from_case(load_case(case_id)), use_llm="--llm" in sys.argv)
    print(result.model_dump_json(indent=2, exclude_none=True) if "--json" in sys.argv else "", end="")
    if "--json" not in sys.argv:
        _print(result)
