import os
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "history"


@pytest.fixture
def synthea_bundle_path() -> Path:
    return SAMPLES / "synthea_coherent_sample_bundle.json"


@pytest.fixture
def mimic_dir() -> Path:
    return SAMPLES / "mimic_demo_subject_10004235"


@pytest.fixture
def mimic_subject() -> str:
    return "10004235"


@pytest.fixture
def intake_text() -> str:
    return (
        "Conditions: type 2 diabetes, high blood pressure, chronic kidney disease stage 3\n"
        "Medications: metformin 500 mg twice daily, lisinopril 10 mg daily, warfarin 5 mg\n"
        "Allergies: penicillin (rash), aspirin\n"
        "Surgeries: appendectomy 2015, knee arthroscopy 2021\n"
        "Doctors: Dr. Lee (cardiology), primary care at Austin Family Clinic\n"
    )


# Keep the suite offline: agents only call AWS when CARERELAY_USE_AWS=1.
os.environ.pop("CARERELAY_USE_AWS", None)
os.environ["CARERELAY_OFFLINE"] = "1"   # Wellness: use the bundled openFDA snapshot, not the network
