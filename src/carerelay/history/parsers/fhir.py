"""Parse a FHIR R4 Bundle (Synthea / Synthea Coherent) into a HistoryProfile.

Deterministic: no network, no LLM. Handles the resource shapes Synthea emits:

* Condition            -> conditions      (code.coding SNOMED, clinicalStatus active/resolved)
* MedicationRequest    -> medications     (medicationCodeableConcept RxNorm or medicationReference -> Medication)
* AllergyIntolerance   -> allergies       (code, reaction.manifestation, criticality)
* Procedure            -> procedures      (code SNOMED, performedPeriod.start)
* Encounter / CareTeam -> care_team, known_specialists (participant displays, encounter type text)
* Patient              -> patient summary
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..risk_flags import derive_risk_flags
from ..schema import CodedItem, HistoryProfile, PatientSummary
from ._specialties import specialties_in_text

SYSTEM_MAP = {
    "http://snomed.info/sct": "snomed",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
    "http://hl7.org/fhir/sid/icd-10-cm": "icd10cm",
    "http://hl7.org/fhir/sid/icd-10": "icd10cm",
    "http://hl7.org/fhir/sid/icd-9-cm": "icd9cm",
    "http://www.ama-assn.org/go/cpt": "cpt",
}


def _first_coding(codeable: dict[str, Any] | None) -> tuple[str | None, str, str]:
    """Return (code, system_key, display) from a CodeableConcept, preferring a known system."""
    if not codeable:
        return None, "text", ""
    codings = codeable.get("coding") or []
    best = None
    for c in codings:
        if c.get("system") in SYSTEM_MAP:
            best = c
            break
    if best is None and codings:
        best = codings[0]
    display = (codeable.get("text") or (best or {}).get("display") or "").strip()
    if best is None:
        return None, "text", display
    return best.get("code"), SYSTEM_MAP.get(best.get("system", ""), "text"), display


def _status_from_condition(res: dict[str, Any]) -> str:
    cs = res.get("clinicalStatus") or {}
    for c in cs.get("coding") or []:
        code = (c.get("code") or "").lower()
        if code in ("active", "recurrence", "relapse"):
            return "active"
        if code in ("resolved", "remission", "inactive"):
            return "resolved"
    if res.get("abatementDateTime") or res.get("abatementString"):
        return "resolved"
    return "unknown"


def _age(birth: str | None, on: date | None = None) -> int | None:
    if not birth:
        return None
    try:
        y, m, d = (int(x) for x in birth[:10].split("-"))
    except ValueError:
        return None
    today = on or date.today()
    return today.year - y - ((today.month, today.day) < (m, d))


def _load(bundle: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(bundle, dict):
        return bundle
    text = str(bundle)
    if isinstance(bundle, Path) or not text.lstrip().startswith(("{", "[")):
        text = Path(text).read_text()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("top-level JSON value is not an object", text[:20], 0)
    return data


def parse_fhir_bundle(bundle: str | Path | dict[str, Any], *, as_of: date | None = None) -> HistoryProfile:
    """Parse a FHIR R4 Bundle (path, JSON string, or dict) into a HistoryProfile."""
    profile = HistoryProfile(source="fhir")
    try:
        data = _load(bundle)
    except (OSError, json.JSONDecodeError) as exc:
        profile.source = "degraded"
        profile.warnings.append(f"Could not read bundle: {exc}")
        return profile

    entries = data.get("entry") or []
    if data.get("resourceType") != "Bundle" or not entries:
        profile.source = "degraded"
        profile.warnings.append("Input is not a FHIR Bundle with entries")
        return profile

    resources: list[dict[str, Any]] = [e.get("resource") or {} for e in entries]
    by_fullurl: dict[str, dict[str, Any]] = {
        e.get("fullUrl", ""): e.get("resource") or {} for e in entries if e.get("fullUrl")
    }
    care_team: list[str] = []
    specialties: set[str] = set()
    seen_meds: set[tuple[str | None, str]] = set()

    for res in resources:
        rt = res.get("resourceType")
        rid = res.get("id")

        if rt == "Patient":
            name = (res.get("name") or [{}])[0]
            profile.patient = PatientSummary(
                patient_id=rid,
                gender=res.get("gender"),
                birth_date=res.get("birthDate"),
                age_years=_age(res.get("birthDate"), as_of),
            )
            del name  # name intentionally not carried into the profile (PHI minimization)

        elif rt == "Condition":
            code, system, display = _first_coding(res.get("code"))
            if not display:
                continue
            profile.conditions.append(
                CodedItem(
                    display=display,
                    code=code,
                    system=system,
                    status=_status_from_condition(res),
                    onset=(res.get("onsetDateTime") or res.get("recordedDate") or "")[:10] or None,
                    source_ref=f"Condition/{rid}",
                )
            )

        elif rt == "MedicationRequest":
            codeable = res.get("medicationCodeableConcept")
            if codeable is None and res.get("medicationReference"):
                ref = res["medicationReference"].get("reference", "")
                med = by_fullurl.get(ref) or {}
                codeable = med.get("code")
            code, system, display = _first_coding(codeable)
            if not display:
                continue
            key = (code, display.lower())
            status = (res.get("status") or "unknown").lower()
            status = "active" if status == "active" else ("stopped" if status in ("stopped", "completed", "cancelled") else status)
            if key in seen_meds:
                # keep the most favourable status if the same drug appears repeatedly
                if status == "active":
                    for m in profile.medications:
                        if (m.code, m.display.lower()) == key:
                            m.status = "active"
                continue
            seen_meds.add(key)
            dose = None
            di = (res.get("dosageInstruction") or [{}])[0]
            if di.get("text"):
                dose = di["text"]
            elif di.get("timing", {}).get("repeat"):
                r = di["timing"]["repeat"]
                dose = f"{r.get('frequency', '?')} per {r.get('period', '?')} {r.get('periodUnit', '')}".strip()
            profile.medications.append(
                CodedItem(
                    display=display,
                    code=code,
                    system=system,
                    status=status,
                    onset=(res.get("authoredOn") or "")[:10] or None,
                    detail=dose,
                    source_ref=f"MedicationRequest/{rid}",
                )
            )

        elif rt == "AllergyIntolerance":
            code, system, display = _first_coding(res.get("code"))
            if not display:
                continue
            reactions = []
            for rx in res.get("reaction") or []:
                for man in rx.get("manifestation") or []:
                    _, _, mdisp = _first_coding(man)
                    if mdisp:
                        reactions.append(mdisp)
            crit = res.get("criticality")
            detail = "; ".join(filter(None, [", ".join(reactions) or None, f"criticality: {crit}" if crit else None]))
            cs = ((res.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code", "active")
            profile.allergies.append(
                CodedItem(
                    display=display,
                    code=code,
                    system=system,
                    status="active" if cs == "active" else "resolved",
                    onset=(res.get("recordedDate") or "")[:10] or None,
                    detail=detail or None,
                    source_ref=f"AllergyIntolerance/{rid}",
                )
            )

        elif rt == "Procedure":
            code, system, display = _first_coding(res.get("code"))
            if not display:
                continue
            when = (res.get("performedPeriod") or {}).get("start") or res.get("performedDateTime") or ""
            profile.procedures.append(
                CodedItem(
                    display=display,
                    code=code,
                    system=system,
                    status=(res.get("status") or "completed").lower(),
                    onset=when[:10] or None,
                    source_ref=f"Procedure/{rid}",
                )
            )
            specialties |= specialties_in_text(display)

        elif rt == "Encounter":
            for t in res.get("type") or []:
                _, _, tdisp = _first_coding(t)
                specialties |= specialties_in_text(tdisp)
            for p in res.get("participant") or []:
                disp = (p.get("individual") or {}).get("display")
                if disp and disp not in care_team:
                    care_team.append(disp)
            sp = (res.get("serviceProvider") or {}).get("display")
            if sp:
                specialties |= specialties_in_text(sp)

        elif rt == "CareTeam":
            for p in res.get("participant") or []:
                disp = (p.get("member") or {}).get("display") or ""
                roles = " ".join((_first_coding(r)[2] or "") for r in (p.get("role") or []))
                if "patient" in roles.lower():
                    continue
                if disp and disp not in care_team:
                    care_team.append(disp)
                specialties |= specialties_in_text(roles)

        elif rt == "Practitioner":
            for q in res.get("qualification") or []:
                _, _, qdisp = _first_coding(q.get("code"))
                specialties |= specialties_in_text(qdisp)

    # Synthea procedures like "Medication Reconciliation" and immunizations are noise for routing; keep
    # them in the list (auditable) but do not derive specialties from them beyond the keyword map.
    profile.care_team = care_team[:20]
    profile.known_specialists = sorted(specialties)
    profile.risk_flags = derive_risk_flags(profile)

    if not (profile.conditions or profile.medications or profile.allergies or profile.procedures):
        profile.warnings.append("Bundle contained no Condition, MedicationRequest, AllergyIntolerance or Procedure")
        profile.source = "degraded"
    return profile
