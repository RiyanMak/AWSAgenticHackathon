"""What the UI expects from each agent: the agent map and the stage payload contracts.

Every agent reports through ``service.handle()`` as ``report["stages"][<stage>]``: a dict with a
``status`` plus the agent's output model dumped into it (``{"status": "ok", **output.model_dump()}``).
The UI renders any stage whose payload validates against the model below, so building an agent
means: produce this shape, put it in the stage dict, done. See docs/FRONTEND.md.

Built agents and where their output sits in the stage dict (``payload()`` below reads it):
  history    stages["history"]["profile"]    carerelay.history.schema.HistoryProfile
  lab        stages["lab"]["result"]         carerelay.schemas.LabFindings (findings: list[Finding])
  radiology  stages["radiology"]["result"]   carerelay.schemas.ImagingFindings
  wellness   stages["wellness"]["plan"]      WellnessPlan from carerelay/wellness/rules.py (top-level
             package, not yet wired into service.handle); the UI reads the ``WellnessView`` subset
Summarize and Next Steps are not built yet; their contracts (``SummarizeOutput``, ``NextStepsOutput``)
are defined here. ``SummarizeOutput`` is the patient-facing view of the architecture's ``CaseRecord``
(one ``LedgerItem`` per ledger entry, plus plain-language title, triage and owner): Summarize owners,
please review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# urgent/soon need an appointment; watch = mention to PCP; none = no follow-up (e.g. simple cyst);
# expected = explained by history; answered = the question the scan or test was ordered for
Triage = Literal["urgent", "soon", "watch", "none", "expected", "answered"]
StageStatus = Literal["ok", "not_implemented", "skipped", "needs_clinical_reevaluation", "demo"]


# ------------------------------------------------------------------------------- agent map


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    task: str
    consumes: str
    produces: str
    hands_to: tuple[str, ...]
    stage: str  # key in report["stages"] that carries this agent's output


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("lab", "Lab Agent", "Read the lab PDF and compare every value to its reference range",
              "labs.pdf", "LabFindings", ("summarize",), "lab"),
    AgentSpec("radiology", "Radiology Agent", "Read the imaging report; separate the answered question from incidental findings",
              "radiology.pdf", "ImagingFindings", ("summarize",), "radiology"),
    AgentSpec("history", "History Agent", "Code conditions, medications and allergies; set risk flags",
              "history.pdf + intake", "HistoryProfile", ("summarize", "wellness"), "history"),
    AgentSpec("summarize", "Summarize", "Merge findings, mark expected vs incidental, keep the incidental ledger",
              "Lab + Radiology + History", "SummarizeOutput", ("wellness", "next_steps"), "summarize"),
    AgentSpec("wellness", "Wellness Agent", "Suggest budget nutrition, activity and OTC options, filtered by allergies and meds",
              "SummarizeOutput + HistoryProfile", "WellnessPlan", ("patient",), "wellness"),
    AgentSpec("next_steps", "Next Steps", "Map each follow-up to a specialty and propose in-network appointments",
              "SummarizeOutput + coverage", "NextStepsOutput", ("insurance", "patient"), "next_steps"),
    AgentSpec("insurance", "Insurance Agent", "Check network, referral, prior auth and cost against the deductible",
              "proposed appointment + coverage", "InsuranceCheck", ("next_steps",), "next_steps"),
)
AGENT = {a.id: a for a in AGENTS}
PARALLEL_FIRST = ("lab", "radiology", "history")


# ------------------------------------------------------------------------- Lab / Radiology


class FindingView(BaseModel):
    """The subset of carerelay Finding (Lab/Radiology agents) the UI reads."""

    model_config = ConfigDict(extra="allow")
    id: str
    source: Literal["lab", "radiology"]
    label: str
    value: str | None = None
    severity: Literal["info", "follow_up", "urgent", "red_flag"] = "info"
    in_impression: bool | None = None
    answers_indication: bool | None = None


# ------------------------------------------------------------------------------ Summarize


class LedgerItem(BaseModel):
    """One row of the incidental ledger: a finding with an owner and a next step."""

    id: str
    title: str = Field(description="Plain-language name, e.g. 'Small spot on your right lung'")
    plain: str = Field(description="One or two sentences a patient understands")
    source: Literal["lab", "radiology", "history", "intake"]
    triage: Triage
    incidental: bool
    in_impression: bool | None = Field(default=None, description="False = only in FINDINGS (classic miss)")
    explained_by: str | None = Field(default=None, description="History condition that makes it expected")
    owner: str = Field(description="Who should act: a specialty or 'Your PCP'")
    followup_services: list[str] = Field(default_factory=list, description="Service keys from data/network/services.json")
    finding_refs: list[str] = Field(default_factory=list, description="Finding ids this row came from")


class SummarizeOutput(BaseModel):
    headline: str = Field(description="One sentence: what the reports mean, answered question first")
    items: list[LedgerItem] = Field(default_factory=list)


# ------------------------------------------------------------------------------- Wellness
# Subset of carerelay/wellness/rules.py WellnessPlan that the UI renders (extra fields allowed).


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExcludedView(_Open):
    name: str
    reasons: list[str] = Field(default_factory=list)


class OTCOptionView(_Open):
    ingredient: str
    brand_example: str | None = None
    purpose: str | None = None


class OTCView(_Open):
    status: Literal["options", "pharmacist_only", "not_applicable"]
    options: list[OTCOptionView] = Field(default_factory=list)
    excluded: list[ExcludedView] = Field(default_factory=list)


class GuidanceView(_Open):
    text: str
    reason: str | None = None


class NutritionView(_Open):
    guidance: list[GuidanceView] = Field(default_factory=list)
    excluded_foods: list[ExcludedView] = Field(default_factory=list)


class ActivityView(_Open):
    weekly_target: str
    cautions: list[str] = Field(default_factory=list)


class WellnessView(_Open):
    status: Literal["plan", "seek_care", "needs_clinical_reevaluation"]
    seek_care_message: str | None = None
    otc: OTCView | None = None
    nutrition: NutritionView | None = None
    activity: ActivityView | None = None


# ------------------------------------------------------------------- Next Steps + Insurance


class InsuranceCheck(BaseModel):
    """One Next Steps -> Insurance round trip (the handoff loop the UI animates)."""

    round: int
    ledger_id: str
    service: str
    provider_id: str
    provider_name: str
    miles: float
    in_network: bool
    verdict: Literal["accepted", "re-propose"]
    note: str


class ProposedAppointment(BaseModel):
    ledger_ids: list[str]
    service: str
    service_name: str
    provider_id: str
    provider_name: str
    clinician: str | None = None
    start: str = Field(description="ISO datetime of the proposed slot")
    miles: float
    patient_pays: float
    cost_note: str
    referral_required: bool = False
    prior_auth_required: bool = False
    status: Literal["proposed", "confirmed"] = "proposed"


class NextStepsOutput(BaseModel):
    appointments: list[ProposedAppointment] = Field(default_factory=list)
    insurance_checks: list[InsuranceCheck] = Field(default_factory=list)
    total_patient_pays: float = 0.0


CONTRACTS: dict[str, type[BaseModel]] = {
    "summarize": SummarizeOutput,
    "wellness": WellnessView,
    "next_steps": NextStepsOutput,
}
PAYLOAD_KEY = {"history": "profile", "lab": "result", "radiology": "result", "wellness": "plan"}


def payload(stage: str, stage_dict: dict) -> dict:
    """The agent's output inside a stage dict (``{}`` when the stage has none)."""
    key = PAYLOAD_KEY.get(stage)
    return (stage_dict.get(key) or {}) if key else stage_dict
