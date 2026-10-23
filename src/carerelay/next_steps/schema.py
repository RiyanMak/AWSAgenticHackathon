"""Next Steps inputs (the contract with Summarize) and outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from carerelay.insurance.schema import CoverageProfile

Triage = Literal["urgent", "soon", "watch", "none"]


class RoutedFinding(BaseModel):
    """One finding as Summarize hands it over: what it is, how soon, and whether it is incidental."""

    id: str
    source: Literal["lab", "radiology", "intake", "history"]
    label: str
    triage: Triage
    incidental: bool = True
    specialty_hint: str | None = None
    site: str | None = None
    size_mm: float | None = None
    evidence: str | None = None
    recommendation: str | None = None
    explained_by: str | None = None
    services: list[str] | None = Field(default=None, description="Set when Summarize already chose services")


class PatientContext(BaseModel):
    zip: str
    availability: dict[str, Any] | None = None       # {"days": ["mon", ...], "times": "morning"}, as in intake
    max_travel_miles: float = 15
    preferred_language: str = "en"
    established_provider_ids: list[str] = Field(default_factory=list)
    display: str = "Patient"                           # name for the Appointment participant; no identifiers needed


class NextStepsRequest(BaseModel):
    findings: list[RoutedFinding]
    coverage: dict[str, Any]                           # FHIR-shaped Coverage
    patient: PatientContext
    today: str = "2026-10-23"


class ServiceStep(BaseModel):
    service: str
    service_name: str
    finding_ids: list[str]
    reasons: list[str]
    triage: Triage
    status: Literal["proposed", "discuss_with_pcp", "no_option_found"]
    due_by: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    clinician: str | None = None
    distance_miles: float | None = None
    in_network: bool | None = None
    established: bool = False
    language_match: bool | None = None
    slot_start: str | None = None
    slot_end: str | None = None
    patient_pays: float | None = None
    allowed_amount: float | None = None
    prior_auth_required: bool = False
    referral_required: bool = False
    search_rounds: int = 0
    appointment: dict[str, Any] | None = None          # FHIR Appointment, status "proposed"; a human confirms
    notes: list[str] = Field(default_factory=list)


class NoAction(BaseModel):
    finding_id: str
    label: str
    reason: str


class NextStepsPlan(BaseModel):
    status: Literal["ok", "needs_clinical_reevaluation"] = "ok"
    method: Literal["rules", "rules+llm"] = "rules"
    steps: list[ServiceStep] = Field(default_factory=list)
    no_action: list[NoAction] = Field(default_factory=list)
    unmapped_findings: list[str] = Field(default_factory=list, description="Finding ids no rule could map")
    coverage: CoverageProfile | None = None
    total_patient_pays: float = 0.0
    summary: str = ""
    caregiver_notes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class ServiceChoice(BaseModel):
    finding_id: str
    services: list[str] = Field(description="Service ids from the catalog only")
    rationale: str = ""


class NextStepsDecision(BaseModel):
    """What the Next Steps model returns. Validated before anything is applied."""

    service_choices: list[ServiceChoice] = Field(
        default_factory=list, description="Only for findings you want to change or that had no rule match")
    patient_explanation: str = Field(description="3-6 plain sentences: what is proposed, in what order, why, and the "
                                                 "estimated cost. Every appointment is only proposed until confirmed.")
    caregiver_notes: list[str] = Field(default_factory=list, description="Up to 4 practical notes (referrals first, "
                                                                         "bring prior reports, etc.)")
