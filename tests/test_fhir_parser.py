import json

from carerelay.history.parsers.fhir import parse_fhir_bundle


def test_parses_synthea_sample(synthea_bundle_path):
    profile = parse_fhir_bundle(synthea_bundle_path)
    assert profile.source == "fhir"
    assert profile.patient.gender in ("male", "female")
    assert profile.patient.age_years is None or profile.patient.age_years > 0
    assert profile.conditions, "expected conditions from the sample bundle"
    assert profile.medications, "expected medications from the sample bundle"
    assert profile.allergies, "the sample bundle was chosen to contain an AllergyIntolerance"
    assert profile.procedures
    assert all(c.system == "snomed" and c.code for c in profile.conditions)
    assert all(m.system == "rxnorm" and m.code for m in profile.medications)
    assert all(c.source_ref and c.source_ref.startswith("Condition/") for c in profile.conditions)
    assert not profile.warnings


def test_medications_deduplicated_and_status_kept(synthea_bundle_path):
    profile = parse_fhir_bundle(synthea_bundle_path)
    keys = [(m.code, m.display.lower()) for m in profile.medications]
    assert len(keys) == len(set(keys))
    assert {m.status for m in profile.medications} <= {"active", "stopped", "unknown", "on-hold", "entered-in-error", "draft"}
    assert profile.active_medications()


def test_accepts_dict_and_json_string(synthea_bundle_path):
    data = json.loads(synthea_bundle_path.read_text())
    from_dict = parse_fhir_bundle(data)
    from_str = parse_fhir_bundle(json.dumps(data))
    assert from_dict.model_dump() == from_str.model_dump()


def test_degrades_on_bad_input(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    profile = parse_fhir_bundle(bad)
    assert profile.source == "degraded"
    assert profile.warnings

    empty = parse_fhir_bundle({"resourceType": "Bundle", "entry": []})
    assert empty.source == "degraded"


def test_risk_flags_from_snomed_codes():
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c1",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes mellitus type 2"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c2",
                    "clinicalStatus": {"coding": [{"code": "resolved"}]},
                    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "72892002", "display": "Normal pregnancy"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "m1",
                    "status": "active",
                    "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "855332", "display": "Warfarin Sodium 5 MG Oral Tablet"}]},
                }
            },
        ],
    }
    profile = parse_fhir_bundle(bundle)
    assert "diabetes" in profile.risk_flags
    assert "anticoagulant" in profile.risk_flags
    assert "pregnancy" not in profile.risk_flags, "resolved pregnancy must not be a current risk"
