"""Typed outputs of the Lab and Radiology agents. Field names follow docs/ARCHITECTURE.md."""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "follow_up", "urgent", "red_flag"]
Status = Literal["ok", "needs_clinical_reevaluation"]


class Finding(BaseModel):
    id: str
    source: Literal["lab", "radiology"]
    label: str                          # e.g. "Potassium", "Solid pulmonary nodule"
    value: str | None = None            # raw lab value with unit, or measurement for imaging
    evidence: str                       # page/row for labs, verbatim report quote for imaging
    confidence: float
    severity: Severity
    # Summarize decides expected vs incidental against the HistoryProfile; specialists leave these unset.
    incidental: bool | None = None
    explained_by: str | None = None
    specialty_hint: str | None = None
    # radiology extras
    site: str | None = None
    size_mm: float | None = None
    in_impression: bool | None = None   # False = only in FINDINGS, the classic missed-follow-up case
    answers_indication: bool | None = None
    recommendation: str | None = None   # radiologist's own recommendation, quoted
    # lab extras
    panel: str | None = None
    observed_at: str | None = None      # collection date; older results are context, not today's visit


class LabRow(BaseModel):
    analyte: str                        # as printed on the report
    key: str | None = None              # normalized analyte key, None if not in our table
    value: float | None = None          # None for qualitative results
    value_text: str                     # raw text, keeps "<0.01" or "Detected"
    unit: str | None = None
    ref_text: str | None = None         # as printed: "3.5-5.1", "<200", ">=60", "Negative"
    ref_low: float | None = None
    ref_high: float | None = None
    ref_low_exclusive: bool = False     # ">60": 60 itself is low
    ref_high_exclusive: bool = False    # "<200": 200 itself is high
    report_flag: str | None = None      # H/L/A as printed by the lab, if any
    flag: Literal["normal", "low", "high", "critical_low", "critical_high", "abnormal", "unknown"] = "unknown"
    panel: str | None = None
    collected: str | None = None
    page: int | None = None


class LabFindings(BaseModel):
    status: Status = "ok"
    extraction_method: Literal["bedrock", "textract", "local_text"] | None = None
    rows: list[LabRow] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    notes: list[str] = Field(default_factory=list)   # audit trail: fallbacks, flag disagreements
    error: str | None = None


class ImagingFindings(BaseModel):
    status: Status = "ok"
    extraction_method: Literal["bedrock", "local_rules"] | None = None
    exam: str | None = None
    indication: str | None = None       # reason for the study; Summarize uses it for incidental tagging
    sections: dict[str, str] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


# ---------- Summarize output, consumed by Wellness and Next Steps ----------
# One shared contract: Finding above (Lab/Radiology) and the History Agent's HistoryProfile.

from carerelay.history.schema import CodedItem, HistoryProfile  # noqa: E402  (re-exported for Wellness)

Triage = Literal["urgent", "soon", "watch", "none"]


class LedgerEntry(BaseModel):
    """Every incidental finding gets a ledger row and must end with a route or an explicit review (SAFETY.md 3)."""

    finding_id: str
    source: Literal["lab", "radiology", "intake", "history"]
    label: str = ""
    evidence: str
    confidence: float
    triage: Triage = "watch"
    specialty_hint: str | None = None
    status: Literal["open", "routed", "confirmed", "reviewed_no_action"] = "open"


class CaseRecord(BaseModel):
    """Summarize output consumed by Wellness and Next Steps."""

    findings: list[Finding] = Field(default_factory=list)   # abnormal results only, incidental/explained_by set
    history: HistoryProfile
    ledger: list[LedgerEntry] = Field(default_factory=list)
    visit_reason: str | None = None     # needed for the incidental definition and OTC symptom match
    patient_age: int | None = None      # SAFETY.md OTC rule 2 (age outside label range)
    human_confirmed: bool = False       # set by the UI after red-flag/urgent review
    triage: dict[str, Triage] = Field(default_factory=dict)   # finding id -> triage, for Next Steps
    red_flags_open: list[str] = Field(default_factory=list)   # red-flag finding ids
    needs_confirmation: list[str] = Field(default_factory=list)  # red-flag/urgent ids pausing care actions until
                                                                 # a human confirms (SAFETY.md guardrail 4)
    summary: str = ""
    critic_notes: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)              # specialist stages that failed or were skipped


__all__ = ["CaseRecord", "CodedItem", "Finding", "HistoryProfile", "ImagingFindings", "LabFindings", "LabRow",
           "LedgerEntry", "Severity", "Status", "Triage"]
