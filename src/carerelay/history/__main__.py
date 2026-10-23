"""CLI: python -m carerelay.history [--fhir BUNDLE] [--mimic-dir DIR --subject ID] [--intake TEXT|FILE] [--no-llm]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import DEFAULT_MODEL_ID, run_history_agent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="carerelay-history", description="CareRelay History Agent")
    p.add_argument("--fhir", help="Path to a FHIR R4 Bundle JSON (Synthea)")
    p.add_argument("--mimic-dir", help="Directory with MIMIC-IV hosp tables (.csv or .csv.gz)")
    p.add_argument("--subject", help="MIMIC subject_id (required with --mimic-dir)")
    p.add_argument("--intake", help="Intake form text, or a path to a text file")
    p.add_argument("--offline", action="store_true", help="Skip Comprehend Medical for intake text")
    p.add_argument("--no-llm", action="store_true", help="Skip the Bedrock summary; parsing only")
    p.add_argument("--model", default=None, help=f"Bedrock model id (default: $BEDROCK_MODEL_ID or {DEFAULT_MODEL_ID})")
    p.add_argument("--region", default=None, help="AWS region for Bedrock and Comprehend Medical")
    p.add_argument("--out", help="Write the profile JSON to this file instead of stdout")
    args = p.parse_args(argv)

    if not (args.fhir or args.mimic_dir or args.intake):
        p.error("provide at least one of --fhir, --mimic-dir/--subject, --intake")
    if args.mimic_dir and not args.subject:
        p.error("--subject is required with --mimic-dir")

    intake_text = None
    if args.intake:
        intake_text = Path(args.intake).read_text() if Path(args.intake).is_file() else args.intake

    profile = run_history_agent(
        fhir_bundle=args.fhir,
        mimic_dir=args.mimic_dir,
        mimic_subject_id=args.subject,
        intake_text=intake_text,
        offline=args.offline,
        use_llm=not args.no_llm,
        model_id=args.model,
        region=args.region,
    )
    payload = json.dumps(profile.model_dump(), indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
