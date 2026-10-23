from carerelay.history.parsers.intake import parse_intake_text, split_sections
from carerelay.history.risk_flags import EXPLAINS, derive_risk_flags, explained_by, nsaid_excluded
from carerelay.history.schema import CodedItem, HistoryProfile


def test_split_sections(intake_text):
    sections = split_sections(intake_text)
    assert sections["conditions"] == ["type 2 diabetes", "high blood pressure", "chronic kidney disease stage 3"]
    assert len(sections["medications"]) == 3
    assert sections["allergies"] == ["penicillin (rash)", "aspirin"]
    assert sections["procedures"] == ["appendectomy 2015", "knee arthroscopy 2021"]
    assert sections["doctors"]


def test_split_sections_handles_nkda_and_no_headers():
    assert split_sections("Allergies: NKDA") == {}
    assert split_sections("asthma, eczema")["conditions"] == ["asthma", "eczema"]


def test_offline_intake_profile(intake_text):
    profile = parse_intake_text(intake_text, offline=True)
    assert profile.source == "intake_text"
    assert [c.display for c in profile.conditions][0] == "type 2 diabetes"
    assert all(c.system == "text" for c in profile.conditions)
    assert profile.allergies[0].display == "penicillin" and profile.allergies[0].detail == "rash"
    assert profile.allergies[1].display == "aspirin"
    assert profile.procedures[0].onset == "2015"
    assert "cardiology" in profile.known_specialists and "primary_care" in profile.known_specialists
    # keyword fallback flags, since nothing is coded offline
    assert {"diabetes", "hypertension", "ckd", "anticoagulant"} <= set(profile.risk_flags)
    assert any("Offline mode" in w for w in profile.warnings)


def test_explained_by_and_nsaid_exclusion():
    profile = HistoryProfile(
        conditions=[CodedItem(display="Type 2 diabetes mellitus", code="E11.9", system="icd10cm", status="active")],
        medications=[],
    )
    profile.risk_flags = derive_risk_flags(profile)
    assert profile.risk_flags == ["diabetes"]
    assert explained_by("Glucose", profile) == ["diabetes"]
    assert explained_by("Hemoglobin A1c", profile) == ["diabetes"]
    assert explained_by("Creatinine", profile) == [], "creatinine is incidental without CKD"
    assert not nsaid_excluded(profile)

    profile.conditions.append(CodedItem(display="CKD stage 3", code="N18.3", system="icd10cm", status="active"))
    profile.risk_flags = derive_risk_flags(profile)
    assert explained_by("Creatinine", profile) == ["ckd"]
    assert nsaid_excluded(profile)


def test_icd9_and_text_fallbacks():
    profile = HistoryProfile(
        conditions=[
            CodedItem(display="Hypertension NOS", code="4019", system="icd9cm", status="active"),
            CodedItem(display="Congestive heart failure", status="active"),  # uncoded text
            CodedItem(display="Diabetes mellitus", code="25000", system="icd9cm", status="resolved"),
        ]
    )
    flags = derive_risk_flags(profile)
    assert "hypertension" in flags and "heart_failure" in flags
    assert "diabetes" not in flags, "resolved conditions do not contribute flags"


def test_every_explains_key_is_a_known_flag():
    known = set()
    from carerelay.history import risk_flags as rf

    known |= set(rf.ICD10_PREFIXES.values()) | set(rf.ICD9_PREFIXES.values()) | set(rf.SNOMED_CODES.values())
    known |= set(rf.TEXT_KEYWORDS.values()) | set(rf.MEDICATION_KEYWORDS.values())
    assert set(EXPLAINS) <= known
