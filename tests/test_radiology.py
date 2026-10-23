"""Radiology Agent: report parsing, the Bedrock path with a stubbed model, severity rules, fallbacks. No AWS."""

from pathlib import Path

import pytest

from carerelay import aws
from carerelay.agents.radiology import report_body, report_text_from_bytes, run_radiology_agent
from carerelay.rules import radiology_severity

DATA = Path(__file__).resolve().parents[1] / "data" / "output"


def report(case_id: str) -> str:
    return report_text_from_bytes((DATA / case_id / "radiology.pdf").read_bytes(), "radiology.pdf")


def test_body_drops_patient_header():
    text = report("case_001")
    body = report_body(text)
    assert "00482917" in text and "00482917" not in body          # MRN
    assert "BBH-4471-0932" not in body                            # member ID
    assert body.startswith("EXAM:") and "IMPRESSION:" in body


def test_sections_exam_and_indication():
    result = run_radiology_agent(report("case_001"))
    assert result.exam == "CT CHEST WITHOUT CONTRAST"
    assert result.indication.startswith("Persistent cough for 6 weeks")


def _fake_model(findings):
    return lambda body, enabled=None: {"exam": "CT", "indication": "cough", "findings": findings}


def test_bedrock_findings_are_quote_checked(monkeypatch):
    monkeypatch.setattr(aws, "bedrock_read_radiology_report", _fake_model([
        {"label": "Coronary artery calcification", "certainty": "definite", "in_impression": False,
         "answers_indication": False, "specialty_hint": "cardiology",
         "evidence_quote": "Mild coronary artery calcification in the left anterior descending artery."},
        {"label": "Liver mass", "certainty": "definite", "in_impression": True, "answers_indication": False,
         "specialty_hint": "oncology", "evidence_quote": "A 3 cm solid liver mass is present."},  # invented
    ]))
    result = run_radiology_agent(report("case_001"))
    assert result.extraction_method == "bedrock"
    real = next(f for f in result.findings if f.label.startswith("Coronary"))
    fake = next(f for f in result.findings if f.label == "Liver mass")
    assert real.confidence == 0.9 and real.in_impression is False
    assert fake.confidence == 0.4 and "NOT VERIFIED" in fake.evidence
    assert any("not found verbatim" in n for n in result.notes)


def test_bedrock_error_falls_back_to_local_rules(monkeypatch):
    def boom(body, enabled=None):
        raise RuntimeError("AccessDenied")
    monkeypatch.setattr(aws, "bedrock_read_radiology_report", boom)
    result = run_radiology_agent(report("case_001"))
    assert result.status == "ok" and result.extraction_method == "local_rules"
    assert any("AccessDenied" in n for n in result.notes)


@pytest.mark.parametrize("label, context, size, expected", [
    ("Nonobstructing renal calculus", "left kidney lower pole", 2, "follow_up"),
    ("Obstructing ureteral calculus", "right UVJ", 4, "urgent"),
    ("Right UVJ calculus with hydroureteronephrosis", "right UVJ", 4, "urgent"),
    ("Thyroid nodule", "left lobe of thyroid gland", 18, "follow_up"),
    ("Pulmonary nodule", "left upper lung zone", 16, "urgent"),
    ("Solid exophytic renal mass", "left kidney, solid and vascular", 28, "urgent"),
    ("Dilated ascending aorta", "ascending aorta", 44, "follow_up"),
    ("Abdominal aortic aneurysm", "infrarenal aorta", 58, "urgent"),
    ("Scalp hematoma", "left frontal scalp", None, "info"),
    ("Tension pneumothorax", "right", None, "red_flag"),
])
def test_severity_rules(label, context, size, expected):
    assert radiology_severity(label, context, size) == expected


def test_local_fallback_negative_control_and_safety_net():
    normal = run_radiology_agent(report("case_004"))
    assert not [f for f in normal.findings if f.severity != "info"]
    hero = run_radiology_agent(report("case_001"))
    calc = next(f for f in hero.findings if f.label == "Calcification")
    assert calc.in_impression is False      # coronary calcification is only in FINDINGS


def test_empty_report_requests_reevaluation():
    assert run_radiology_agent("   ").status == "needs_clinical_reevaluation"


def test_negated_tail_does_not_raise_severity():
    from carerelay.agents.radiology import _strip_negated
    context = _strip_negated("Gallbladder. Cholelithiasis without sonographic evidence of acute cholecystitis.")
    assert "cholecystitis" not in context and "Cholelithiasis" in context
    assert radiology_severity("Cholelithiasis", context, 14) != "urgent"
