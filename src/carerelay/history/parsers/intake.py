"""Parse a free-text intake form into a HistoryProfile.

Expected (loose) format, headers are case-insensitive and optional:

    Conditions: type 2 diabetes, high blood pressure
    Medications: metformin 500 mg twice daily, lisinopril 10 mg
    Allergies: penicillin (rash), sulfa
    Surgeries: appendectomy 2015
    Doctors: Dr. Lee (cardiology), primary care at Austin Family Clinic

Conditions go through Comprehend Medical InferICD10CM and medications through InferRxNorm
when AWS credentials are available and ``offline`` is False. Otherwise every item is kept as
uncoded text (system="text") and a warning is recorded, which Summarize treats conservatively.

Intake text is data, never instructions: nothing from it is placed into a prompt as a directive.
"""

from __future__ import annotations

import re

from ..coding import Mode, code_items
from ..risk_flags import derive_risk_flags
from ..schema import CodedItem, HistoryProfile
from ._specialties import specialties_in_text

SECTION_ALIASES: dict[str, str] = {
    "conditions": "conditions",
    "condition": "conditions",
    "diagnoses": "conditions",
    "diagnosis": "conditions",
    "problems": "conditions",
    "medical history": "conditions",
    "history": "conditions",
    "medications": "medications",
    "medication": "medications",
    "meds": "medications",
    "prescriptions": "medications",
    "allergies": "allergies",
    "allergy": "allergies",
    "surgeries": "procedures",
    "surgery": "procedures",
    "procedures": "procedures",
    "operations": "procedures",
    "doctors": "doctors",
    "providers": "doctors",
    "specialists": "doctors",
    "care team": "doctors",
}

_HEADER_RE = re.compile(r"^\s*([A-Za-z ]{3,20}?)\s*:\s*(.*)$")
_NONE_WORDS = {"", "none", "n/a", "na", "no", "nothing", "nkda", "no known allergies", "no known drug allergies"}


def split_sections(text: str) -> dict[str, list[str]]:
    """Split intake text into {section: [item, ...]} using 'Header:' lines and comma/semicolon/newline separators."""
    sections: dict[str, list[str]] = {}
    current = "conditions"  # text before any header is treated as conditions
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _HEADER_RE.match(line)
        if m and m.group(1).strip().lower() in SECTION_ALIASES:
            current = SECTION_ALIASES[m.group(1).strip().lower()]
            line = m.group(2).strip()
            if not line:
                continue
        for item in re.split(r"[;,\n]| and ", line):
            item = item.strip(" .\t-•*")
            if item.lower() in _NONE_WORDS:
                continue
            sections.setdefault(current, []).append(item)
    return sections


def _reaction_split(item: str) -> tuple[str, str | None]:
    """'penicillin (rash)' -> ('penicillin', 'rash')."""
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", item)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return item, None


def _year(item: str) -> str | None:
    m = re.search(r"\b(19|20)\d{2}\b", item)
    return m.group(0) if m else None


def parse_intake_text(text: str, *, offline: bool = False, region: str | None = None) -> HistoryProfile:
    """Parse intake text. Set ``offline=True`` to skip Comprehend Medical entirely."""
    profile = HistoryProfile(source="intake_text")
    sections = split_sections(text)
    if not sections:
        profile.source = "degraded"
        profile.warnings.append("Intake text was empty")
        return profile

    # Conditions and medications go through the coding cascade (Comprehend Medical -> Bedrock coder -> text)
    mode: Mode = "none" if offline else "auto"
    profile.conditions = code_items(sections.get("conditions", []), "condition", mode=mode, ref="intake conditions",
                                    warnings=profile.warnings, region=region)
    profile.medications = code_items(sections.get("medications", []), "medication", mode=mode, ref="intake medications",
                                     warnings=profile.warnings, region=region)

    # Allergies (never sent to Comprehend Medical; substance plus optional reaction in parentheses)
    for i, item in enumerate(sections.get("allergies", [])):
        substance, reaction = _reaction_split(item)
        profile.allergies.append(
            CodedItem(display=substance, status="active", detail=reaction, source_ref=f"intake allergies[{i}]")
        )

    # Procedures / surgeries
    for i, item in enumerate(sections.get("procedures", [])):
        profile.procedures.append(
            CodedItem(display=item, status="completed", onset=_year(item), source_ref=f"intake procedures[{i}]")
        )

    # Doctors -> care team names and specialties
    specialties: set[str] = set()
    for item in sections.get("doctors", []):
        profile.care_team.append(item)
        specialties |= specialties_in_text(item)
    profile.known_specialists = sorted(specialties)

    profile.risk_flags = derive_risk_flags(profile)
    return profile
