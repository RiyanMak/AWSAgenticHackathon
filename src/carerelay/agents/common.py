import json

from carerelay import aws
from carerelay.schemas import Finding


def summarize(kind: str, findings: list[Finding], fallback: str, notes: list[str],
              use_aws: bool | None = None) -> str:
    slim = [f.model_dump(include={"label", "value", "severity", "observed_at", "site", "size_mm",
                                  "recommendation", "answers_indication"}, exclude_none=True) for f in findings]
    try:
        return aws.bedrock_summarize(kind, json.dumps(slim), enabled=use_aws) or fallback
    except Exception as e:
        notes.append(f"Bedrock summary failed, used template: {type(e).__name__}: {e}")
        return fallback
