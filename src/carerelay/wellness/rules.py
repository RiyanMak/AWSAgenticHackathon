"""Deterministic Wellness rules (SAFETY.md section 2).

`build_plan(case)` is the single source of truth for what the patient sees. The LLM in
`agent.py` only explains this plan; it never adds a drug, dose or food.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from carerelay.history.risk_flags import NSAID_EXCLUSION_FLAGS
from carerelay.schemas import CaseRecord, Finding
from carerelay.wellness import knowledge as K
from carerelay.wellness.clients import food_snapshot, get_otc_label

BANNER = "Not medical advice. Clinician review required before acting on anything below."
DISCLAIMER = (
    "CareRelay is a hackathon prototype that uses synthetic or public data. It is not a clinical "
    "system and does not provide medical advice, diagnosis or treatment. Findings must be reviewed "
    "by a licensed clinician. In an emergency call your local emergency number."
)
PHARMACIST_LINE = "Talk to a pharmacist or clinician before taking any over-the-counter medicine."
SEEK_CARE = (
    "One or more results need prompt attention from a clinician. Please contact your care team "
    "or seek care now rather than relying on home remedies. In an emergency call your local "
    "emergency number."
)


# --- Output schema ----------------------------------------------------------


class Excluded(BaseModel):
    name: str
    reasons: list[str]


class OTCOption(BaseModel):
    ingredient: str
    brand_example: str | None
    purpose: str | None
    directions_from_label: str | None  # quoted verbatim, never generated
    do_not_use: str | None
    ask_doctor: str | None
    stop_use: str | None
    label_set_id: str | None
    provenance: str


class OTCSection(BaseModel):
    status: Literal["options", "pharmacist_only", "not_applicable"]
    options: list[OTCOption] = Field(default_factory=list)
    excluded: list[Excluded] = Field(default_factory=list)  # "excluded because of your history"
    blocking_reasons: list[str] = Field(default_factory=list)
    pharmacist_note: str = PHARMACIST_LINE
    source: str = K.SOURCES["openfda_label"]


class Guidance(BaseModel):
    text: str
    reason: str
    source: str | None
    rule: Literal["cited", "prototype"]


class FoodItem(BaseModel):
    name: str
    group: str
    per_100g: dict[str, float] | None
    fdc_id: int | None
    note: str | None = None


class NutritionSection(BaseModel):
    sodium_target_mg: int
    guidance: list[Guidance]
    foods: list[FoodItem]
    excluded_foods: list[Excluded] = Field(default_factory=list)
    budget_note: str = (
        "Staples chosen for low cost and long shelf life (dried, frozen, store-brand). "
        "Prices are not checked."
    )
    source: str = K.SOURCES["fooddata_central"]


class ActivitySection(BaseModel):
    intensity: Literal["standard", "gentle"]
    weekly_target: str
    exercises: list[dict]
    cautions: list[str]
    source: str = K.SOURCES["cdc_activity"]


class WellnessPlan(BaseModel):
    status: Literal["plan", "seek_care", "needs_clinical_reevaluation"]
    banner: str = BANNER
    disclaimer: str = DISCLAIMER
    seek_care_message: str | None = None
    otc: OTCSection | None = None
    nutrition: NutritionSection | None = None
    activity: ActivitySection | None = None
    considered_findings: list[str] = Field(default_factory=list)  # finding ids, for the audit log
    audit: list[str] = Field(default_factory=list)  # one line per rule decision


# --- Helpers ----------------------------------------------------------------


def _has_word(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


def _snippet(text: str, term: str, width: int = 70) -> str:
    m = re.search(re.escape(term), text, re.IGNORECASE)
    if not m:
        return ""
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    if start:  # snap to word boundaries
        start = text.find(" ", start) + 1 or start
    if end < len(text):
        end = text.rfind(" ", m.end(), end) if text.rfind(" ", m.end(), end) > 0 else end
    return ("..." if start else "") + text[start:end].strip() + ("..." if end < len(text) else "")


def _lab_flags(case: CaseRecord, terms: tuple[str, ...]) -> list[Finding]:
    return [f for f in case.findings if f.source == "lab" and any(_has_word(f.label, t) for t in terms)]


def _active_meds(case: CaseRecord) -> list[str]:
    return [m.display.lower() for m in case.history.active_medications()]


# Questionnaire entries like "Never smoker" or "No chronic conditions" are negations, not conditions.
_NEGATED = re.compile(r"^\s*(no|never|denies|denied|not|without|negative for)\b", re.IGNORECASE)


def _conditions_text(case: CaseRecord) -> list[str]:
    active = [c.display.lower() for c in case.history.active_conditions() if not _NEGATED.match(c.display)]
    return active + [f.lower().replace("_", " ") for f in case.history.risk_flags]


def _has_hypertension(case: CaseRecord) -> bool:
    return any("hypertension" in c or "high blood pressure" in c for c in _conditions_text(case))


def _care_first(case: CaseRecord) -> list[str]:
    return [s for s in K.CARE_FIRST_SYMPTOMS if case.visit_reason and _has_word(case.visit_reason, s)]


# --- Gate -------------------------------------------------------------------


def red_flag_gate(case: CaseRecord) -> tuple[bool, list[str]]:
    """Return (block_plan, audit). Red flags always replace the plan (SAFETY.md rule 6);
    urgent findings block it until a human has confirmed (SAFETY.md section 3)."""
    audit = []
    # Summarize's own lists are authoritative; severity on the findings is the backstop.
    red = sorted(set(case.red_flags_open) | {f.id for f in case.findings if f.severity == "red_flag"})
    urgent = sorted((set(case.needs_confirmation) | {f.id for f in case.findings if f.severity == "urgent"}) - set(red))
    if red:
        audit.append(f"gate: red_flag open {red}; wellness plan replaced with seek-care message")
        return True, audit
    if urgent and not case.human_confirmed:
        audit.append(f"gate: urgent {urgent} awaiting human confirmation; wellness plan withheld")
        return True, audit
    if urgent:
        audit.append(f"gate: urgent {urgent} confirmed by human; plan shown after seek-care message")
    return False, audit


# --- OTC --------------------------------------------------------------------


def _otc_candidates(visit_reason: str | None) -> list[str]:
    if not visit_reason:
        return []
    seen: list[str] = []
    for kw, names in K.OTC_CANDIDATES.items():
        if _has_word(visit_reason, kw):
            seen += [n for n in names if n not in seen]
    return seen


def otc_section(case: CaseRecord, audit: list[str]) -> OTCSection:
    candidates = _otc_candidates(case.visit_reason)
    if not candidates:
        audit.append(f"otc: no symptom match for visit reason {case.visit_reason!r}; no OTC options")
        return OTCSection(status="not_applicable")

    # Rule 2: deterministic whole-section blocks.
    blocking = [f"visit reason mentions {s!r}, which needs a clinician rather than self-care medicine"
                for s in _care_first(case)]
    for flag in sorted(set(case.history.risk_flags) & K.OTC_BLOCKING_FLAGS):
        blocking.append(f"history risk flag: {flag}")
    for f in _lab_flags(case, K.KIDNEY_LABS):
        blocking.append(f"kidney lab flagged: {f.label} ({f.id})")
    for f in _lab_flags(case, K.LIVER_LABS):
        blocking.append(f"liver lab flagged: {f.label} ({f.id})")
    if case.patient_age is None:
        blocking.append("age not provided, so label age limits cannot be checked")
    elif case.patient_age < K.MIN_OTC_AGE:
        blocking.append(f"age {case.patient_age} is under {K.MIN_OTC_AGE}")
    if case.history.is_degraded():
        blocking.append("medical history could not be read reliably, so allergy and medication checks are incomplete")
    blocking += [f"incomplete input ({g}), so kidney, liver and other checks cannot be completed" for g in case.gaps]
    if blocking:
        audit.append(f"otc: pharmacist_only, blocked by {blocking}")
        return OTCSection(status="pharmacist_only", blocking_reasons=blocking)

    allergies = [a.display.lower() for a in case.history.allergies]
    allergy_classes = {c for a in allergies for kw, cs in K.ALLERGY_CLASSES.items() if kw in a for c in cs}
    meds = _active_meds(case)
    med_classes = {c for m in meds for kw, cs in K.MEDICATION_CLASSES.items() if kw in m for c in cs}
    conditions = _conditions_text(case)
    nsaid_labs = _lab_flags(case, K.NSAID_BLOCKING_LABS)
    nsaid_flags = sorted(set(case.history.risk_flags) & NSAID_EXCLUSION_FLAGS)  # History's own NSAID rule

    options, excluded = [], []
    for name in candidates:
        classes = K.INGREDIENT_CLASSES.get(name, set())
        reasons = []
        label = get_otc_label(name)
        if label is None:
            excluded.append(Excluded(name=name.lower(), reasons=["no FDA label available to ground directions"]))
            continue
        # Rule 2a: allergies.
        if hit := classes & allergy_classes:
            reasons.append(f"allergy in your history ({', '.join(allergies)}) covers {', '.join(sorted(hit))}")
        elif any(name.lower().split()[0] in a for a in allergies):
            reasons.append(f"allergy to {name.lower()} in your history")
        # Duplicate therapy.
        if hit := classes & med_classes:
            reasons.append(f"you already take a {', '.join(sorted(hit))} medicine")
        # Rule 3: NSAIDs blocked by flagged kidney or potassium labs.
        if "nsaid" in classes and nsaid_labs:
            labs = ", ".join(f.label for f in nsaid_labs)
            reasons.append(f"NSAIDs avoided because {labs} was flagged (conservative prototype rule)")
        if "nsaid" in classes and nsaid_flags:
            reasons.append(f"NSAIDs avoided because of {', '.join(nsaid_flags)} in your history")
        # Rule 2a: label text names a medicine or condition from the history.
        label_text = " ".join(
            label.get(k, "") for k in ("do_not_use", "ask_doctor", "ask_doctor_or_pharmacist", "drug_interactions")
        )
        for med in meds:
            for kw, terms in K.MEDICATION_LABEL_TERMS.items():
                if kw in med:
                    for t in terms:
                        if t in label_text.lower():
                            reasons.append(f"label warns about {t} (you take {med}): \"{_snippet(label_text, t)}\"")
                            break
        condition_hits: dict[str, str] = {}  # label term -> first matching history entry
        for cond in conditions:
            for kw, terms in K.CONDITION_LABEL_TERMS.items():
                if kw in cond:
                    for t in terms:
                        if t in label_text.lower():
                            condition_hits.setdefault(t, cond)
                            break
        for t, cond in condition_hits.items():
            reasons.append(f"the label's warnings mention {t} (your history: {cond})")
        do_not_use = label.get("do_not_use", "").lower()
        for t in K.VISIT_LABEL_TERMS:
            if case.visit_reason and _has_word(case.visit_reason, t) and t in do_not_use:
                reasons.append(f"label says do not use for {t} symptoms: \"{_snippet(label['do_not_use'], t)}\"")
                break
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            excluded.append(Excluded(name=name.lower(), reasons=reasons))
            audit.append(f"otc: excluded {name}: {reasons}")
            continue
        options.append(
            OTCOption(
                ingredient=name.lower(),
                brand_example=label.get("brand_name"),
                purpose=label.get("purpose"),
                directions_from_label=label.get("dosage_and_administration"),
                do_not_use=label.get("do_not_use"),
                ask_doctor=label.get("ask_doctor"),
                stop_use=label.get("stop_use"),
                label_set_id=label.get("set_id"),
                provenance=label.get("provenance", "openFDA"),
            )
        )
        audit.append(f"otc: included {name} ({label.get('provenance')}, set_id {label.get('set_id')})")
    status = "options" if options else "pharmacist_only"
    return OTCSection(status=status, options=options, excluded=excluded)


# --- Nutrition --------------------------------------------------------------


def nutrition_section(case: CaseRecord, audit: list[str]) -> NutritionSection:
    conds = _conditions_text(case)
    flags = set(case.history.risk_flags)
    guidance: list[Guidance] = []

    hypertension = _has_hypertension(case)
    sodium = K.DASH_SODIUM_LOWER_MG if hypertension else K.DASH_SODIUM_MG
    guidance.append(Guidance(
        text=f"Aim for no more than {sodium:,} mg of sodium a day. Cook from dried or frozen staples and "
             "choose canned foods labeled 'no salt added'.",
        reason="high blood pressure in your history" if hypertension else "general DASH target",
        source=K.SOURCES["dash"], rule="cited",
    ))
    guidance.append(Guidance(
        text="Build meals around vegetables, fruits, whole grains, beans and lean protein, and limit sweets "
             "and sugar-sweetened drinks.",
        reason="DASH eating pattern", source=K.SOURCES["dash"], rule="cited",
    ))
    diabetes = "diabetes" in flags or any(_has_word(c, "diabetes") for c in conds)  # not "prediabetes"
    glucose_lab = _lab_flags(case, ("glucose", "hba1c", "a1c", "hemoglobin a1c"))
    if diabetes or glucose_lab or "prediabetes" in flags:
        guidance.append(Guidance(
            text="Pair starchy foods with beans, eggs or tofu, keep portions of rice and pasta moderate, and "
                 "drink water instead of juice or soda.",
            reason=("diabetes in your history" if diabetes else
                    f"{glucose_lab[0].label} was flagged" if glucose_lab else "prediabetes in your history"),
            source=None, rule="prototype",
        ))
    potassium_lab = _lab_flags(case, ("potassium",))
    low_potassium_needed = "ckd" in flags or bool(potassium_lab)
    if low_potassium_needed:
        why = "kidney disease in your history" if "ckd" in flags else f"{potassium_lab[0].label} was flagged"
        guidance.append(Guidance(
            text="Ask your clinician how much potassium is right for you. Avoid salt substitutes, which often "
                 "contain potassium, until you have asked.",
            reason=why, source=None, rule="prototype",
        ))

    allergies = [a.display.lower() for a in case.history.allergies]
    allergen_tags = {tag for a in allergies for kw, tag in K.FOOD_ALLERGENS.items() if kw in a}
    snapshot = food_snapshot().get("foods", {})
    foods, excluded = [], []
    for name, (_, tags, group) in K.STAPLES.items():
        entry = snapshot.get(name)
        per100 = entry["per_100g"] if entry else None
        reasons = []
        if hit := tags & allergen_tags:
            reasons.append(f"food allergy in your history ({', '.join(sorted(hit))})")
        if low_potassium_needed:
            if per100 is None or "potassium_mg" not in per100:
                reasons.append("potassium content unknown and potassium is a concern for you")
            elif per100["potassium_mg"] > K.HIGH_POTASSIUM_MG_PER_100G:
                reasons.append(
                    f"high in potassium ({per100['potassium_mg']:.0f} mg per 100 g, FoodData Central)"
                )
        if reasons:
            excluded.append(Excluded(name=name, reasons=reasons))
            continue
        foods.append(FoodItem(
            name=name, group=group, per_100g=per100, fdc_id=entry["fdc_id"] if entry else None,
            note=None if entry else "nutrient data not loaded; run scripts/refresh_wellness_snapshots.py",
        ))
    audit.append(
        f"nutrition: sodium {sodium} mg, diabetes={diabetes}, potassium_caution={low_potassium_needed}, "
        f"foods {len(foods)} kept / {len(excluded)} excluded"
    )
    return NutritionSection(sodium_target_mg=sodium, guidance=guidance, foods=foods, excluded_foods=excluded)


# --- Activity ---------------------------------------------------------------


def activity_section(case: CaseRecord, audit: list[str]) -> ActivitySection:
    texts = [f.label.lower() for f in case.findings] + _conditions_text(case)
    triggers = sorted({t for t in K.CARDIOPULMONARY_TERMS for x in texts if t in x} | set(_care_first(case)))
    cautions = [
        "Stop and seek care if you have chest pain, severe shortness of breath, fainting or new weakness.",
        "Increase slowly. Some movement most days is better than none.",
    ]
    if case.visit_reason and _has_word(case.visit_reason, "back pain"):
        cautions.append("See a doctor if back pain does not improve in a few weeks (OrthoInfo, AAOS): "
                        + K.SOURCES["orthoinfo_back_pain"])
    if "anticoagulant" in case.history.risk_flags:
        cautions.append("You take a blood thinner, so choose low fall-risk activities and hold onto support.")
    if triggers:
        audit.append(f"activity: gentle only, triggered by {triggers}")
        return ActivitySection(
            intensity="gentle",
            weekly_target="Short, easy walks only until your clinician clears you for more.",
            exercises=[e for e in K.BASE_EXERCISES if e["name"] in ("Walking", "Sit-to-stand")],
            cautions=[f"Your results mention {', '.join(triggers)}, so ask your clinician before "
                      "exercising harder."] + cautions,
        )
    audit.append("activity: standard CDC adult target")
    return ActivitySection(
        intensity="standard",
        weekly_target="Work up to 150 minutes a week of moderate activity, plus muscle-strengthening on 2 or "
                      "more days (CDC adult guidelines).",
        exercises=K.BASE_EXERCISES,
        cautions=cautions,
    )


# --- Entry point ------------------------------------------------------------


def build_plan(case: CaseRecord) -> WellnessPlan:
    """Deterministic wellness plan. Never raises: failures return needs_clinical_reevaluation."""
    try:
        blocked, audit = red_flag_gate(case)
        ids = [f.id for f in case.findings]
        if blocked:
            return WellnessPlan(status="seek_care", seek_care_message=SEEK_CARE, considered_findings=ids, audit=audit)
        urgent_confirmed = any(f.severity == "urgent" for f in case.findings)
        return WellnessPlan(
            status="plan",
            seek_care_message=SEEK_CARE if urgent_confirmed else None,
            otc=otc_section(case, audit),
            nutrition=nutrition_section(case, audit),
            activity=activity_section(case, audit),
            considered_findings=ids,
            audit=audit,
        )
    except Exception as e:  # SAFETY.md guardrail 2: explicit failure, not a crash
        return WellnessPlan(
            status="needs_clinical_reevaluation",
            seek_care_message="We could not build a wellness plan. Please ask your clinician for guidance.",
            audit=[f"error: {type(e).__name__}: {e}"],
        )
