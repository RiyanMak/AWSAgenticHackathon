"""Shared data contracts from docs/ARCHITECTURE.md.

`Finding` and `HistoryProfile` follow the architecture doc. A few fields the doc
implies but does not spell out are marked "added"; owners of the Lab, History
and Summarize agents should review them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "follow_up", "urgent", "red_flag"]


class Finding(BaseModel):
    id: str
    source: Literal["lab", "radiology"]
    label: str  # e.g. "Potassium", "Nodule"
    value: str | None = None  # raw value or score
    evidence: str  # page/row or image region reference
    confidence: float
    severity: Severity
    incidental: bool
    explained_by: str | None = None  # history condition or medication id, when expected
    specialty_hint: str | None = None


class CodedItem(BaseModel):
    """One coded history entry (condition, medication, allergy or procedure)."""

    system: str | None = None  # e.g. ICD-10-CM, SNOMED, RxNorm
    code: str | None = None
    display: str
    status: str | None = None  # active, resolved, ...
    detail: str | None = None  # dose text, reaction, criticality, onset or date
    confidence: float | None = None  # Comprehend Medical score, free-text path only


class HistoryProfile(BaseModel):
    conditions: list[CodedItem] = Field(default_factory=list)
    medications: list[CodedItem] = Field(default_factory=list)
    allergies: list[CodedItem] = Field(default_factory=list)
    procedures: list[CodedItem] = Field(default_factory=list)
    known_specialists: list[str] = Field(default_factory=list)
    # Derived deterministically: ckd, pregnancy, anticoagulant, liver, diabetes, hypertension
    risk_flags: list[str] = Field(default_factory=list)
    # "degraded" (added): parsing failed or codes were low confidence; see SAFETY.md section 3
    source: Literal["pdf", "fhir", "csv", "intake_text", "degraded"]


class LedgerEntry(BaseModel):
    finding_id: str
    source: Literal["lab", "radiology"]
    evidence: str
    confidence: float
    specialty_hint: str | None = None
    status: Literal["open", "routed", "confirmed", "reviewed_no_action"] = "open"


class CaseRecord(BaseModel):
    """Summarize output consumed by Wellness and Next Steps."""

    findings: list[Finding] = Field(default_factory=list)  # abnormal results only
    history: HistoryProfile
    ledger: list[LedgerEntry] = Field(default_factory=list)
    visit_reason: str | None = None  # added: needed for the incidental definition and OTC symptom match
    patient_age: int | None = None  # added: SAFETY.md OTC rule 2 (age outside label range)
    human_confirmed: bool = False  # added: set by the UI after red-flag/urgent review
