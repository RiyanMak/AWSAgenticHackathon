"""Deterministic risk flags and the expected-finding table.

The LLM never derives these. Summarize uses ``EXPLAINS`` to decide whether an abnormal
lab value or imaging label is expected for a known condition (``explained_by``) or incidental.
Wellness uses the flags as hard filters on OTC options (see docs/SAFETY.md).

Code tables are intentionally small and labeled as a prototype rule set.
"""

from __future__ import annotations

import re

from .schema import CodedItem, HistoryProfile

# ICD-10-CM prefixes (match on the start of the code, dots removed)
ICD10_PREFIXES: dict[str, str] = {
    "N18": "ckd",
    "R73": "prediabetes",  # R73.03 prediabetes, R73.0x abnormal glucose
    "E10": "diabetes",
    "E11": "diabetes",
    "E13": "diabetes",
    "I10": "hypertension",
    "I11": "hypertension",
    "I12": "hypertension",
    "I13": "hypertension",
    "I15": "hypertension",
    "I16": "hypertension",
    "K70": "liver",
    "K71": "liver",
    "K72": "liver",
    "K73": "liver",
    "K74": "liver",
    "K75": "liver",
    "K76": "liver",
    "K77": "liver",
    "Z33": "pregnancy",
    "Z34": "pregnancy",
    "I50": "heart_failure",
    "I48": "atrial_fibrillation",
    "J44": "copd",
    "J45": "asthma",
    "E78": "hyperlipidemia",
    "Z7901": "anticoagulant",  # long-term (current) use of anticoagulants
    "D68": "bleeding_disorder",
    "C": "cancer_history",
}

# ICD-9-CM prefixes
ICD9_PREFIXES: dict[str, str] = {
    "585": "ckd",
    "250": "diabetes",
    "401": "hypertension",
    "402": "hypertension",
    "403": "hypertension",
    "404": "hypertension",
    "405": "hypertension",
    "571": "liver",
    "V22": "pregnancy",
    "V23": "pregnancy",
    "428": "heart_failure",
    "42731": "atrial_fibrillation",
    "496": "copd",
    "493": "asthma",
    "272": "hyperlipidemia",
    "V5861": "anticoagulant",
    "286": "bleeding_disorder",
}

# SNOMED CT codes commonly emitted by Synthea
SNOMED_CODES: dict[str, str] = {
    "44054006": "diabetes",  # Diabetes mellitus type 2
    "46635009": "diabetes",  # Diabetes mellitus type 1
    "15777000": "prediabetes",
    "59621000": "hypertension",
    "431855005": "ckd",  # CKD stage 1
    "431856006": "ckd",  # stage 2
    "433144002": "ckd",  # stage 3
    "431857002": "ckd",  # stage 4
    "46177005": "ckd",  # end stage renal disease
    "127013003": "ckd",  # diabetic renal disease
    "88805009": "heart_failure",  # chronic congestive heart failure
    "84114007": "heart_failure",
    "49436004": "atrial_fibrillation",
    "72892002": "pregnancy",  # normal pregnancy
    "77386006": "pregnancy",
    "195967001": "asthma",
    "13645005": "copd",
    "87433001": "copd",  # pulmonary emphysema
    "55822004": "hyperlipidemia",
    "128302006": "liver",  # chronic hepatitis C
    "19943007": "liver",  # cirrhosis
    "254837009": "cancer_history",  # malignant neoplasm of breast
    "363406005": "cancer_history",  # malignant tumor of colon
    "254637007": "cancer_history",  # non-small cell lung cancer
}

# Display-text fallback when codes are missing or unknown (lower-case substring match)
TEXT_KEYWORDS: dict[str, str] = {
    "chronic kidney": "ckd",
    "renal failure": "ckd",
    "end stage renal": "ckd",
    "prediabetes": "prediabetes",  # checked before "diabetes" (see flags_for_condition)
    "diabetes": "diabetes",
    "hypertension": "hypertension",
    "high blood pressure": "hypertension",
    "cirrhosis": "liver",
    "hepatitis": "liver",
    "liver disease": "liver",
    "pregnan": "pregnancy",
    "heart failure": "heart_failure",
    "atrial fibrillation": "atrial_fibrillation",
    "copd": "copd",
    "emphysema": "copd",
    "asthma": "asthma",
    "hyperlipidemia": "hyperlipidemia",
    "high cholesterol": "hyperlipidemia",
    "cancer": "cancer_history",
    "carcinoma": "cancer_history",
    "lymphoma": "cancer_history",
}

# Medication name keywords (lower-case substring match on display text)
MEDICATION_KEYWORDS: dict[str, str] = {
    "warfarin": "anticoagulant",
    "coumadin": "anticoagulant",
    "apixaban": "anticoagulant",
    "eliquis": "anticoagulant",
    "rivaroxaban": "anticoagulant",
    "xarelto": "anticoagulant",
    "dabigatran": "anticoagulant",
    "edoxaban": "anticoagulant",
    "heparin": "anticoagulant",
    "enoxaparin": "anticoagulant",
    "insulin": "diabetes",
    "metformin": "diabetes",
    "glipizide": "diabetes",
    "prednisone": "steroid",
    "methotrexate": "immunosuppressed",
    "tacrolimus": "immunosuppressed",
    "lithium": "lithium",  # NSAID interaction
    "clopidogrel": "antiplatelet",
    "aspirin": "antiplatelet",
}

# Which lab analytes / imaging labels a flag can explain. Used by Summarize for ``explained_by``.
# Keys are risk flags; values are lower-case substrings matched against finding labels.
EXPLAINS: dict[str, list[str]] = {
    "diabetes": ["glucose", "hba1c", "hemoglobin a1c", "a1c"],
    # prediabetes deliberately explains nothing: an A1c that is still high, or has crossed into the
    # diabetes range, is actionable, not "already known" (matches the bundled answer keys).
    "prediabetes": [],
    "ckd": ["creatinine", "bun", "urea nitrogen", "potassium", "egfr", "phosphate", "phosphorus", "bicarbonate"],
    "heart_failure": ["cardiomegaly", "effusion", "bnp", "edema", "enlarged cardiomediastinum"],
    "hypertension": ["cardiomegaly"],
    "liver": ["alt", "ast", "bilirubin", "albumin", "inr", "alkaline phosphatase", "platelet"],
    "anticoagulant": ["inr", "prothrombin", "pt ", "ptt"],
    "copd": ["emphysema", "hyperinflation", "lung opacity"],
    "asthma": ["hyperinflation"],
    "hyperlipidemia": ["ldl", "cholesterol", "triglyceride", "hdl"],
    "atrial_fibrillation": ["irregular", "atrial fibrillation"],
    "cancer_history": ["nodule", "mass", "lesion"],
}

# Flags that are hard exclusions for OTC NSAIDs (see docs/SAFETY.md rules 2 and 3)
NSAID_EXCLUSION_FLAGS = {"ckd", "liver", "pregnancy", "anticoagulant", "bleeding_disorder", "heart_failure", "lithium"}


def _norm_code(code: str | None) -> str:
    return (code or "").replace(".", "").upper().strip()


def flags_for_condition(item: CodedItem) -> set[str]:
    flags: set[str] = set()
    code = _norm_code(item.code)
    if item.system == "icd10cm" and code:
        for prefix, flag in ICD10_PREFIXES.items():
            if code.startswith(prefix):
                flags.add(flag)
    elif item.system == "icd9cm" and code:
        for prefix, flag in ICD9_PREFIXES.items():
            if code.startswith(prefix):
                flags.add(flag)
    elif item.system == "snomed" and code in SNOMED_CODES:
        flags.add(SNOMED_CODES[code])
    if not flags:  # fall back to the display text
        text = (item.display or "").lower()
        for kw, flag in TEXT_KEYWORDS.items():
            if kw in text:
                flags.add(flag)
        if "prediabetes" in flags:
            flags.discard("diabetes")  # "prediabetes" contains "diabetes"
    return flags


def flags_for_medication(item: CodedItem) -> set[str]:
    text = (item.display or "").lower()
    return {flag for kw, flag in MEDICATION_KEYWORDS.items() if kw in text}


def derive_risk_flags(profile: HistoryProfile) -> list[str]:
    """Return the sorted, de-duplicated risk flags for a profile. Pure function, no I/O."""
    flags: set[str] = set()
    for c in profile.active_conditions():
        flags |= flags_for_condition(c)
    for m in profile.active_medications():
        flags |= flags_for_medication(m)
    # Pregnancy from a resolved condition is not a current risk; only active ones count (handled above).
    return sorted(flags)


def explained_by(finding_label: str, profile: HistoryProfile) -> list[str]:
    """Return the risk flags (if any) that would explain an abnormal finding with this label.

    Example: explained_by("Glucose", profile_with_diabetes) -> ["diabetes"].
    Summarize puts the first match into ``Finding.explained_by``; an empty list means incidental.
    """
    label = (finding_label or "").lower()
    hits = []
    for flag in profile.risk_flags:
        for needle in EXPLAINS.get(flag, []):
            if re.search(r"\b" + re.escape(needle.strip()) + r"\b", label) or needle in label:
                hits.append(flag)
                break
    return hits


def nsaid_excluded(profile: HistoryProfile) -> bool:
    return bool(set(profile.risk_flags) & NSAID_EXCLUSION_FLAGS)
