"""Run the Lab and Radiology agents in parallel on one bundled case from data/output.

    python -m carerelay.run_case case_001          # local parsing only
    python -m carerelay.run_case case_001 --aws    # Bedrock extraction and summaries
    python -m carerelay.run_case case_001 --json   # full typed output
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "output"


def run_case(case_id: str):
    from carerelay.agents.lab import run_lab_agent
    from carerelay.agents.radiology import report_text_from_bytes, run_radiology_agent

    folder = DATA / case_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        lab = pool.submit(run_lab_agent, (folder / "labs.pdf").read_bytes())
        rad = pool.submit(run_radiology_agent,
                          report_text_from_bytes((folder / "radiology.pdf").read_bytes(), "radiology.pdf"))
        return lab.result(), rad.result()


def _print(lab, rad) -> None:
    print(f"RADIOLOGY [{rad.status}, {rad.extraction_method}] {rad.exam}")
    print(f"  indication: {rad.indication}")
    for f in rad.findings:
        where = "impression" if f.in_impression else "FINDINGS ONLY" if f.in_impression is False else "?"
        tag = " (answers indication)" if f.answers_indication else ""
        print(f"  {f.id:6} {f.severity:9} {f.confidence:.2f}  {f.label}{f' {f.value}' if f.value else ''}"
              f"  [{where}] -> {f.specialty_hint}{tag}")
    print(f"  summary: {rad.summary}")
    print(f"\nLAB [{lab.status}, {lab.extraction_method}] {len(lab.rows)} rows")
    for f in lab.findings:
        print(f"  {f.id:6} {f.severity:9} {f.label} {f.value} ({f.observed_at}) -> {f.specialty_hint}")
    print(f"  summary: {lab.summary}")
    for n in lab.notes + rad.notes:
        print(f"  note: {n}")


if __name__ == "__main__":
    if "--aws" in sys.argv:
        os.environ["CARERELAY_USE_AWS"] = "1"
    case = next((a for a in sys.argv[1:] if not a.startswith("--")), "case_001")
    lab, rad = run_case(case)
    if "--json" in sys.argv:
        print('{"lab": ' + lab.model_dump_json(indent=2, exclude_none=True) +
              ',\n"radiology": ' + rad.model_dump_json(indent=2, exclude_none=True) + "}")
    else:
        _print(lab, rad)
