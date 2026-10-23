"""Pydantic schemas shared by the History Agent and downstream agents (Summarize, Wellness, Next Steps)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CodeSystem = Literal["icd10cm", "icd9cm", "icd10pcs", "icd9pcs", "snomed", "rxnorm", "cpt", "text"]
ProfileSource = Literal["pdf", "fhir", "csv", "intake_text", "degraded"]
CodeSource = Literal["document", "comprehend_medical", "llm"]


class CodedItem(BaseModel):
    """One coded fact from the history (a condition, a medication, an allergy or a procedure)."""

    display: str = Field(description="Human-readable name, e.g. 'Type 2 diabetes mellitus'")
    code: str | None = Field(default=None, description="Code in the given system, or None when uncoded")
    system: CodeSystem = Field(default="text", description="Code system the code belongs to")
    status: str | None = Field(default=None, description="active | resolved | stopped | completed | unknown")
    onset: str | None = Field(default=None, description="ISO date or free text for when it started / was done")
    detail: str | None = Field(default=None, description="Dose text, reaction, criticality, or other context")
    confidence: float | None = Field(default=None, description="Model confidence 0..1 when the code was inferred")
    code_source: CodeSource | None = Field(
        default=None, description="document = printed in the source, comprehend_medical or llm = inferred"
    )
    source_ref: str | None = Field(default=None, description="Resource id, row reference, or text span for audit")


class PatientSummary(BaseModel):
    patient_id: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    age_years: int | None = None


class HistoryProfile(BaseModel):
    """Structured medical history consumed by Summarize, Wellness and Next Steps."""

    patient: PatientSummary = Field(default_factory=PatientSummary)
    conditions: list[CodedItem] = Field(default_factory=list)
    medications: list[CodedItem] = Field(default_factory=list)
    allergies: list[CodedItem] = Field(default_factory=list)
    procedures: list[CodedItem] = Field(default_factory=list)
    family_history: list[CodedItem] = Field(
        default_factory=list, description="Condition in display, relation and age at onset in detail"
    )
    social_history: dict[str, str] = Field(
        default_factory=dict, description="Tobacco, alcohol, occupation, living situation, as written"
    )
    care_team: list[str] = Field(default_factory=list, description="Provider display names seen in the history")
    known_specialists: list[str] = Field(
        default_factory=list, description="Specialties the patient already sees (lower-case, e.g. 'cardiology')"
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Deterministic flags: ckd, diabetes, hypertension, liver, pregnancy, anticoagulant, ...",
    )
    source: ProfileSource = "degraded"
    document_kind: str | None = Field(
        default=None, description="For pdf input: pcp_record or patient_questionnaire"
    )
    no_known_allergies: bool = Field(default=False, description="Source explicitly states no known allergies")
    warnings: list[str] = Field(default_factory=list, description="Parse problems; non-empty means review the input")
    summary: str = Field(default="", description="2-3 sentence plain-language summary (LLM-written)")
    clinician_notes: list[str] = Field(
        default_factory=list, description="Short notes for the reviewing clinician (LLM-written)"
    )

    def active_conditions(self) -> list[CodedItem]:
        return [c for c in self.conditions if (c.status or "active") in ("active", "unknown")]

    def active_medications(self) -> list[CodedItem]:
        return [m for m in self.medications if (m.status or "active") in ("active", "unknown")]

    def is_degraded(self) -> bool:
        return self.source == "degraded"


class HistoryNarrative(BaseModel):
    """What the LLM is asked to produce on top of the deterministic profile."""

    summary: str = Field(description="2-3 sentences a patient could understand. No new facts.")
    clinician_notes: list[str] = Field(
        default_factory=list,
        description="Up to 5 short notes: gaps, duplicates, things to confirm with the patient.",
    )
