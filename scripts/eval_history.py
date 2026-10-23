"""Score the History Agent against the 10 bundled cases, with AWS calls enabled.

Runs the full pipeline per case (PDF parse -> coding cascade -> Bedrock summary) and prints a
scorecard against the case file's history block. Needs AWS credentials; Comprehend Medical is
optional (the Bedrock coder takes over when it is denied).

    .venv/bin/python scripts/eval_history.py [--offline] [--cases case_001,case_004] [--out eval.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carerelay.history import run_history_agent  # noqa: E402
from carerelay.history.risk_flags import explained_by  # noqa: E402


def ingredient(s: str) -> str:
    return re.split(r"[\s/,(-]", s.strip())[0].lower()


def score(case: dict, profile) -> dict:
    h = case["history"]
    exp_codes = {c["icd10"] for c in h["conditions"]}
    got_codes = {c.code for c in profile.conditions if c.code}
    exp_meds = [m for m in h["medications"]]
    got_meds = profile.medications
    med_name_hits = sum(
        1 for m in exp_meds if any(ingredient(m["display"]) in (g.display + " " + (g.detail or "")).lower() for g in got_meds)
    )
    med_code_hits = sum(1 for m in exp_meds if any(g.code == m["rxnorm"] for g in got_meds))
    exp_all = [a["substance"] for a in h["allergies"]]
    all_hits = sum(1 for a in exp_all if any(ingredient(a) in g.display.lower() or g.display.lower() in a.lower() for g in profile.allergies))
    explained = [
        (i["finding"], explained_by(i["finding"], profile))
        for i in case["answer_key"]
        if i["incidental"] and explained_by(i["finding"], profile)
    ]
    return {
        "case": case["case_id"],
        "kind": h["source"],
        "cond_recall": round(len(exp_codes & got_codes) / len(exp_codes), 2) if exp_codes else None,
        "cond_precision": round(len(exp_codes & got_codes) / len(got_codes), 2) if got_codes else None,
        "cond_extra": sorted(got_codes - exp_codes),
        "cond_missed": sorted(exp_codes - got_codes),
        "med_name_recall": round(med_name_hits / len(exp_meds), 2) if exp_meds else None,
        "med_code_match": round(med_code_hits / len(exp_meds), 2) if exp_meds else None,
        "allergy_recall": round(all_hits / len(exp_all), 2) if exp_all else None,
        "procedures": f"{len(profile.procedures)}/{len(h['procedures'])}",
        "risk_flags": profile.risk_flags,
        "explains_incidental": explained,
        "summary_ok": bool(profile.summary),
        "warnings": profile.warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="no AWS calls (parse only)")
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--out", help="write per-case results JSON here")
    args = ap.parse_args()

    paths = sorted((ROOT / "data" / "cases").glob("case_*.json"))
    if args.cases:
        wanted = set(args.cases.split(","))
        paths = [p for p in paths if p.stem in wanted]
    results = []
    for path in paths:
        case = json.loads(path.read_text())
        pdf = ROOT / "data" / "output" / case["case_id"] / "history.pdf"
        t0 = time.time()
        profile = run_history_agent(history_pdf=pdf, offline=args.offline, use_llm=not args.offline)
        r = score(case, profile)
        r["seconds"] = round(time.time() - t0, 1)
        r["profile"] = profile.model_dump()
        results.append(r)
        print(
            f"{r['case']} {r['kind']:<22} cond R/P {r['cond_recall']}/{r['cond_precision']}  "
            f"med name {r['med_name_recall']} code {r['med_code_match']}  allergy {r['allergy_recall']}  "
            f"proc {r['procedures']}  flags {r['risk_flags']}  summary {'yes' if r['summary_ok'] else 'no'}  {r['seconds']}s"
        )
        if r["cond_extra"] or r["cond_missed"]:
            print(f"    extra codes {r['cond_extra']}  missed {r['cond_missed']}")
        if r["explains_incidental"]:
            print(f"    explains incidental: {r['explains_incidental']}")
        for w in r["warnings"]:
            print(f"    warn: {w[:140]}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
