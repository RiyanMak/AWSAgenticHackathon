"""Deterministic Summarize rules: expected vs incidental, and triage (urgent / soon / watch / none).

PROTOTYPE rules, labeled as ours, not a guideline. Thresholds that cite a source say so; the rest are judgment
calls tuned to be conservative (when unsure, a finding is routed rather than dropped).
"""

from __future__ import annotations

import re
from datetime import date

from carerelay.history.risk_flags import explained_by as history_explains
from carerelay.history.schema import HistoryProfile
from carerelay.rules import normalize_analyte
from carerelay.schemas import Finding, LabRow, Triage

# Radiology: benign or non-actionable descriptions (route nowhere, but stay in the ledger as reviewed).
RAD_NONE_TERMS = [
    "simple", "too small to characterize", "atelectasis", "limited evaluation", "not visualized", "degenerative",
    "aortic knob", "atherosclerotic", "mucosal thickening", "volume loss", "modic", "disc bulge", "desiccation",
    "foraminal narrowing", "facet", "hematoma", "contusion", "granuloma",
]
# Radiology: real but slow-moving; mention to the PCP, no appointment.
RAD_WATCH_TERMS = [
    "emphysema", "hyperinflation", "steatosis", "small vessel", "meningioma", "extra-axial", "nonobstructing",
    "non-obstructing", "stable", "lung-rads 2", "benign",
]
INFECTION_KEYS = {"influenza_a", "influenza_b", "sars_cov_2", "rsv"}
ELECTROLYTE_KEYS = {"sodium", "potassium", "calcium"}
OLD_RESULT_DAYS = 180


def _has(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z-]){re.escape(term)}", text) is not None


def radiology_triage(f: Finding, patient_age: int | None) -> Triage:
    text = " ".join(filter(None, [f.label, f.site])).lower()
    if f.severity in ("red_flag", "urgent"):
        return "urgent"
    if f.answers_indication:
        # the ordering clinician owns the answer; route only if it still needs a specialist or is stable/benign
        if any(_has(text, t) for t in RAD_WATCH_TERMS):
            return "watch"
        return "soon" if _actionable(text) or (f.severity == "follow_up" and f.recommendation) else "none"
    if any(_has(text, t) for t in RAD_NONE_TERMS):
        return "none"
    # ACR incidental thyroid nodule: work up at >= 15 mm (age >= 35) or >= 10 mm (age < 35)
    if "thyroid" in text and f.size_mm is not None:
        threshold = 15 if (patient_age or 35) >= 35 else 10
        if f.size_mm < threshold:
            return "none"
    if any(_has(text, t) for t in RAD_WATCH_TERMS):
        return "watch"
    return "soon" if f.severity == "follow_up" else "none"


def _actionable(text: str) -> bool:
    """Indication-answering findings that still need a specialist (stone, gallstones, spinal stenosis)."""
    text = re.sub(r"\b(without|no)\b.*$", "", text)   # "degenerative changes without stenosis"
    return any(_has(text, t) for t in ("uvj", "ureter", "obstructing", "cholelithiasis", "gallstone",
                                       "stenosis", "anterolisthesis", "hydronephrosis"))


def lab_triage(f: Finding, row: LabRow | None, history: HistoryProfile, today: date) -> Triage:
    if f.severity in ("red_flag", "urgent"):
        return "urgent"
    key = normalize_analyte(f.label)
    if key in INFECTION_KEYS:
        return "none"   # answers the visit (e.g. flu swab for fever); the ordering clinician manages it
    value = row.value if row else None
    low = row is not None and row.flag in ("low", "critical_low")
    if key in ELECTROLYTE_KEYS:
        triage: Triage = "soon"
    elif key == "hba1c":
        triage = "soon" if value is not None and value >= 6.5 else "watch"   # ADA: >= 6.5% is the diabetes range
    elif key == "hemoglobin":
        triage = "soon" if low else "watch"     # anemia matters more with an anticoagulant or a fall
    elif key == "egfr":
        triage = "soon" if value is not None and value < 30 else "watch"
    else:
        triage = "watch"
    observed = f.observed_at or (row.collected if row else None)
    if triage == "soon" and observed and (today - date.fromisoformat(observed[:10])).days > OLD_RESULT_DAYS:
        triage = "watch"   # an old result is context for the PCP, not a reason to rush
    return triage


def explained(f: Finding, history: HistoryProfile) -> str | None:
    """History condition/medication flags that explain the finding, or the visit indication for imaging."""
    if f.answers_indication:
        return "visit indication"
    if history.source == "degraded":
        return None     # SAFETY.md 3: unreadable history -> treat everything as incidental
    flags = history_explains(f.label, history)
    return ", ".join(flags) if flags else None
