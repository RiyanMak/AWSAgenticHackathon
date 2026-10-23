from carerelay.history.parsers.mimic import parse_mimic_subject


def test_parses_demo_subject(mimic_dir, mimic_subject):
    profile = parse_mimic_subject(mimic_dir, mimic_subject)
    assert profile.source == "csv"
    assert profile.patient.patient_id == mimic_subject
    assert profile.patient.gender in ("M", "F")
    assert profile.conditions and profile.medications
    assert all(c.system in ("icd9cm", "icd10cm") for c in profile.conditions)
    # every diagnosis should have resolved to a long_title from d_icd_diagnoses
    assert not any(c.display.startswith("ICD-") for c in profile.conditions)
    assert any("no allergy table" in w for w in profile.warnings)


def test_prescriptions_deduplicated_and_latest_admission_active(mimic_dir, mimic_subject):
    profile = parse_mimic_subject(mimic_dir, mimic_subject)
    names = [m.display.lower() for m in profile.medications]
    assert len(names) == len(set(names))
    active = profile.active_medications()
    assert active and len(active) < len(profile.medications)
    assert any("latest admission" in w for w in profile.warnings)


def test_unknown_subject_is_degraded(mimic_dir):
    profile = parse_mimic_subject(mimic_dir, "999999")
    assert profile.source == "degraded"


def test_missing_dir_is_degraded(tmp_path):
    profile = parse_mimic_subject(tmp_path, "1")
    assert profile.source == "degraded"
    assert profile.warnings
