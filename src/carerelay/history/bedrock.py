"""Shared Bedrock model factory for the History Agent (narrative and the fallback coder).

Model selection: explicit ``model_id`` > ``BEDROCK_MODEL_ID`` env > ``DEFAULT_MODEL_ID``.
Verified invokable on 2026-10-23 in us-east-1 and us-west-2 on a personal account. The hackathon
account has its own allowlist: run ``aws bedrock list-inference-profiles`` and set the env var.
"""

from __future__ import annotations

import os

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def resolve_model_id(model_id: str | None = None) -> str:
    return model_id or os.environ.get("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID


def resolve_region(region: str | None = None) -> str | None:
    return region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")


def make_bedrock_model(model_id: str | None = None, region: str | None = None, *, temperature: float = 0.2, max_tokens: int = 1500):
    """Build a Strands BedrockModel. Imported lazily so parsers work without strands installed."""
    from strands.models import BedrockModel

    # temperature is intentionally not sent: Claude Sonnet 5 on Bedrock rejects it ("deprecated for this model").
    return BedrockModel(
        model_id=resolve_model_id(model_id),
        region_name=resolve_region(region),
        max_tokens=max_tokens,
    )
