"""Build the Next Steps patient context from intake answers, the patient record and the history care team."""

from __future__ import annotations

from typing import Any

from carerelay.network import net

from .schema import PatientContext


def established_provider_ids(care_team: list[str]) -> list[str]:
    """Match care-team display names ("Helen Park, MD, Pecan Senior Care") to directory providers."""
    ids = []
    for display in care_team:
        low = display.lower()
        for p in net().providers().values():
            if p["clinician"] and p["clinician"].lower() in low and p["provider_id"] not in ids:
                ids.append(p["provider_id"])
    return ids


def patient_context(intake: dict[str, Any] | None, patient: dict[str, Any], care_team: list[str]) -> PatientContext:
    intake = intake or {}
    return PatientContext(
        zip=patient["address"][0]["postalCode"],
        availability=intake.get("availability"),
        max_travel_miles=intake.get("max_travel_miles", 15),
        preferred_language=intake.get("preferred_language", "en"),
        established_provider_ids=established_provider_ids(care_team),
    )
