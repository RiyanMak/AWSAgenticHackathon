"""Thin wrapper over Amazon Comprehend Medical for the free-text intake path.

Only two operations are used: ``InferICD10CM`` (conditions) and ``InferRxNorm`` (medications).
Both take ``Text`` (UTF-8, max 20,000 bytes) and return ``Entities`` with per-entity
``ICD10CMConcepts`` / ``RxNormConcepts`` lists ranked by ``Score``.

Pricing: per 100-character unit (see docs/AWS_SETUP.md). Text sent here must be synthetic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:  # boto3 is a hard dependency, but keep import errors readable in offline test runs
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

    class BotoCoreError(Exception):  # type: ignore[no-redef]
        pass

    class ClientError(Exception):  # type: ignore[no-redef]
        pass

    class NoCredentialsError(Exception):  # type: ignore[no-redef]
        pass


MAX_BYTES = 20_000


@dataclass
class InferredConcept:
    text: str
    code: str | None
    description: str | None
    score: float | None
    begin: int
    end: int
    negated: bool = False
    category: str | None = None


class ComprehendMedicalError(RuntimeError):
    """Raised when Comprehend Medical cannot be called; callers fall back to uncoded text."""


_client = None


def _client_or_raise(region: str | None = None):
    global _client
    if boto3 is None:
        raise ComprehendMedicalError("boto3 is not installed")
    if _client is None:
        _client = boto3.client(
            "comprehendmedical",
            region_name=region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1",
        )
    return _client


def _truncate(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_BYTES:
        return text
    return raw[:MAX_BYTES].decode("utf-8", errors="ignore")


def _is_negated(entity: dict[str, Any]) -> bool:
    return any(t.get("Name") == "NEGATION" for t in entity.get("Traits") or [])


def _top(concepts: list[dict[str, Any]]) -> tuple[str | None, str | None, float | None]:
    if not concepts:
        return None, None, None
    best = max(concepts, key=lambda c: c.get("Score", 0.0))
    return best.get("Code"), best.get("Description"), best.get("Score")


def infer_icd10cm(text: str, region: str | None = None) -> list[InferredConcept]:
    """Map condition mentions in ``text`` to ICD-10-CM codes."""
    try:
        resp = _client_or_raise(region).infer_icd10_cm(Text=_truncate(text))
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        raise ComprehendMedicalError(str(exc)) from exc
    out = []
    for ent in resp.get("Entities", []):
        code, desc, score = _top(ent.get("ICD10CMConcepts", []))
        out.append(
            InferredConcept(
                text=ent.get("Text", ""),
                code=code,
                description=desc,
                score=score,
                begin=ent.get("BeginOffset", 0),
                end=ent.get("EndOffset", 0),
                negated=_is_negated(ent),
                category=ent.get("Category"),
            )
        )
    return out


def infer_rxnorm(text: str, region: str | None = None) -> list[InferredConcept]:
    """Map medication mentions in ``text`` to RxNorm concepts."""
    try:
        resp = _client_or_raise(region).infer_rx_norm(Text=_truncate(text))
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        raise ComprehendMedicalError(str(exc)) from exc
    out = []
    for ent in resp.get("Entities", []):
        code, desc, score = _top(ent.get("RxNormConcepts", []))
        dose_bits = [
            a.get("Text", "")
            for a in ent.get("Attributes") or []
            if a.get("Type") in ("DOSAGE", "STRENGTH", "FREQUENCY", "ROUTE_OR_MODE", "FORM")
        ]
        out.append(
            InferredConcept(
                text=" ".join([ent.get("Text", "")] + dose_bits).strip(),
                code=code,
                description=desc,
                score=score,
                begin=ent.get("BeginOffset", 0),
                end=ent.get("EndOffset", 0),
                negated=_is_negated(ent),
                category=ent.get("Category"),
            )
        )
    return out
