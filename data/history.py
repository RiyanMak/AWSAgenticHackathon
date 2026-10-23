"""Medical history: FHIR-shaped resources from a case's `history` block.

Two sources, set by history["source"]:
  pcp_record             printed health summary from the patient's PCP (coded)
  patient_questionnaire  new-patient form typed by the patient; items carry
                         "as_written" text, and the codes are what the History
                         agent should infer from it
Conditions use ICD-10-CM; medications and drug allergies use ingredient-level
(IN) or multi-ingredient (MIN) RxNorm codes. Procedures are text only.
"""

from __future__ import annotations

ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SOURCES = {"pcp_record", "patient_questionnaire"}


def _concept(text: str, system: str | None = None, code: str | None = None) -> dict:
    out = {"text": text}
    if code:
        out["coding"] = [{"system": system, "code": code, "display": text}]
    return out


def _note(item: dict) -> list[dict]:
    notes = [item["note"]] if item.get("note") else []
    if item.get("as_written"):
        notes.append(f"Patient wrote: {item['as_written']}")
    return [{"text": n} for n in notes]


def to_fhir(history: dict) -> list[dict]:
    """Condition, MedicationStatement, AllergyIntolerance, Procedure,
    FamilyMemberHistory, social-history Observation and CareTeam resources."""
    reported = history["source"] == "patient_questionnaire"
    verification = {"text": "unconfirmed" if reported else "confirmed"}
    res: list[dict] = []

    for c in history["conditions"]:
        r = {
            "resourceType": "Condition",
            "clinicalStatus": {"text": c["status"]},
            "verificationStatus": verification,
            "category": [{"text": "problem-list-item"}],
            "code": _concept(c["display"], ICD10, c["icd10"]),
            "onsetDateTime": c["onset"],
        }
        if n := _note(c):
            r["note"] = n
        res.append(r)

    for m in history["medications"]:
        r = {
            "resourceType": "MedicationStatement",
            "status": m["status"],
            "medicationCodeableConcept": _concept(m["display"], RXNORM, m["rxnorm"]),
            "dosage": [{"text": m["dosage"]}],
            "informationSource": {"display": "Patient" if reported else m["prescriber"]},
        }
        if n := _note(m):
            r["note"] = n
        res.append(r)

    for a in history["allergies"]:
        r = {
            "resourceType": "AllergyIntolerance",
            "clinicalStatus": {"text": "active"},
            "verificationStatus": verification,
            "category": [a["category"]],
            "criticality": a["criticality"],
            "code": _concept(a["substance"], RXNORM, a.get("rxnorm")),
            "onsetDateTime": a["onset"],
            "reaction": [{"manifestation": [{"text": a["reaction"]}]}],
        }
        if n := _note(a):
            r["note"] = n
        res.append(r)
    if history.get("no_known_allergies"):
        res.append(
            {
                "resourceType": "AllergyIntolerance",
                "clinicalStatus": {"text": "active"},
                "verificationStatus": verification,
                "code": {"text": "No known allergies"},
            }
        )

    for p in history["procedures"]:
        r = {"resourceType": "Procedure", "status": "completed", "code": {"text": p["display"]}, "performedDateTime": p["date"]}
        if n := _note(p):
            r["note"] = n
        res.append(r)

    for f in history["family_history"]:
        cond = {"code": {"text": f["condition"]}}
        if "onset_age" in f:
            cond["onsetAge"] = {"value": f["onset_age"], "unit": "a"}
        r = {"resourceType": "FamilyMemberHistory", "status": "completed", "relationship": {"text": f["relation"]}, "condition": [cond]}
        if n := _note(f):
            r["note"] = n
        res.append(r)

    for label, value in history["social_history"].items():
        res.append(
            {
                "resourceType": "Observation",
                "status": "final",
                "category": [{"text": "social-history"}],
                "code": {"text": label},
                "valueString": value,
            }
        )

    if history["care_team"]:
        res.append(
            {
                "resourceType": "CareTeam",
                "status": "active",
                "participant": [
                    {"role": [{"text": m["role"]}], "member": {"display": f"{m['name']}, {m['organization']}"}}
                    for m in history["care_team"]
                ],
            }
        )
    return res
