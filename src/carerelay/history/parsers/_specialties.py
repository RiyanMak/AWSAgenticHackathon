"""Keyword map from free text (encounter types, roles, doctor lists) to specialty names.

Shared by the FHIR and intake parsers. Output strings are the specialties used by the
Scheduling Agent's specialty table, so keep them lower-case and stable.
"""

from __future__ import annotations

SPECIALTY_KEYWORDS: dict[str, str] = {
    "cardiolog": "cardiology",
    "heart doctor": "cardiology",
    "pulmonolog": "pulmonology",
    "lung doctor": "pulmonology",
    "nephrolog": "nephrology",
    "kidney doctor": "nephrology",
    "endocrinolog": "endocrinology",
    "diabetes clinic": "endocrinology",
    "gastroenterolog": "gastroenterology",
    "hepatolog": "hepatology",
    "oncolog": "oncology",
    "hematolog": "hematology",
    "neurolog": "neurology",
    "orthoped": "orthopedics",
    "orthopaed": "orthopedics",
    "rheumatolog": "rheumatology",
    "dermatolog": "dermatology",
    "psychiatr": "psychiatry",
    "obstetric": "obstetrics",
    "gynecolog": "gynecology",
    "urolog": "urology",
    "ophthalmolog": "ophthalmology",
    "eye doctor": "ophthalmology",
    "otolaryngolog": "otolaryngology",
    "ent doctor": "otolaryngology",
    "allerg": "allergy_immunology",
    "physical therap": "physical_therapy",
    "physiotherap": "physical_therapy",
    "primary care": "primary_care",
    "family medicine": "primary_care",
    "general practi": "primary_care",
    "internal medicine": "primary_care",
    "pcp": "primary_care",
    "dentist": "dentistry",
    "radiolog": "radiology",
    "surgeon": "surgery",
    "surgery": "surgery",
}


def specialties_in_text(text: str) -> set[str]:
    low = (text or "").lower()
    return {spec for kw, spec in SPECIALTY_KEYWORDS.items() if kw in low}
