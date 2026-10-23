"""Summarize: merge, expected vs incidental, triage, ledger, critic, confirmation gate. No AWS."""

from datetime import date
from functools import cache

import pytest

from carerelay.agents.radiology import report_text_from_bytes, run_radiology_agent
from carerelay.agents.lab import run_lab_agent
from carerelay.history import build_history_profile
from carerelay.history.schema import HistoryProfile
from carerelay.next_steps.schema import PatientContext
from carerelay.schemas import Finding, LabFindings
from carerelay.service import find_data_dir
from carerelay.summarize import agent as summarize_agent
from carerelay.summarize import build_case_record, run_summarize, to_next_steps_request
from carerelay.summarize.agent import CriticReport, Dispute
from carerelay.summarize.rules import lab_triage, radiology_triage

OUT = find_data_dir() / "output"
CASE_IDS = [f"case_{i:03d}" for i in range(1, 11)]


@cache
def inputs(case_id):
    folder = OUT / case_id
    history = build_history_profile(history_pdf=folder / "history.pdf", offline=True)
    lab = run_lab_agent((folder / "labs.pdf").read_bytes())
    rad = run_radiology_agent(report_text_from_bytes((folder / "radiology.pdf").read_bytes(), "radiology.pdf"))
    return history, lab, rad


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_record_invariants(case_id):
    r = build_case_record(*inputs(case_id))
    ids = {f.id for f in r.findings}
    assert set(r.triage) == ids
    assert {e.finding_id for e in r.ledger} == {f.id for f in r.findings if f.incidental}
    for e in r.ledger:
        assert e.status == ("reviewed_no_action" if r.triage[e.finding_id] == "none" else "routed")
    for f in r.findings:
        assert f.incidental == (f.explained_by is None)
    assert set(r.needs_confirmation) == {f.id for f in r.findings if f.severity in ("urgent", "red_flag")}
    assert r.gaps == [] and r.critic_notes == []
    assert r.visit_reason and r.patient_age


def test_known_condition_explains_finding():
    r = build_case_record(*inputs("case_001"))       # PCP record lists hyperlipidemia
    ldl = next(f for f in r.findings if f.label == "LDL Cholesterol")
    assert not ldl.incidental and "hyperlipidemia" in ldl.explained_by
    a1c = next(f for f in r.findings if f.label == "Hemoglobin A1c")
    assert a1c.incidental and r.triage[a1c.id] == "watch"


def test_degraded_or_missing_history_treats_all_as_incidental():
    _, lab, rad = inputs("case_001")
    for history in (None, HistoryProfile(source="degraded")):
        r = build_case_record(history, lab, rad)
        assert all(f.incidental for f in r.findings) and r.gaps


def test_failed_lab_stage_is_a_gap_not_a_crash():
    history, _, rad = inputs("case_001")
    bad = LabFindings(status="needs_clinical_reevaluation", error="unreadable")
    r = build_case_record(history, bad, rad)
    assert any("lab" in g for g in r.gaps) and all(f.source == "radiology" for f in r.findings)


def test_critic_flags_lab_finding_without_source_row():
    history, lab, rad = inputs("case_002")
    tampered = lab.model_copy(update={"findings": lab.findings + [Finding(
        id="lab-99", source="lab", label="Potassium", value="9.9 mmol/L", evidence="planted", confidence=0.95,
        severity="follow_up")]})
    r = build_case_record(history, tampered, rad)
    planted = next(f for f in r.findings if f.id == "lab-99")
    assert planted.confidence == 0.3 and any("lab-99" in n for n in r.critic_notes)


def test_confirmation_gate():
    history, lab, rad = inputs("case_007")             # solid renal mass -> urgent
    assert build_case_record(history, lab, rad).needs_confirmation
    assert build_case_record(history, lab, rad, human_confirmed=True).needs_confirmation == []


def rad(label, severity="follow_up", **kw):
    return Finding(id="r", source="radiology", label=label, evidence="q", confidence=0.9, severity=severity, **kw)


@pytest.mark.parametrize("finding, age, expected", [
    (rad("Thyroid nodule", site="Right thyroid lobe", size_mm=11), 66, "none"),    # ACR: < 15 mm at age >= 35
    (rad("Thyroid nodule", site="Left thyroid lobe", size_mm=18), 58, "soon"),
    (rad("Thyroid nodule", size_mm=11), 29, "soon"),                               # >= 10 mm under 35
    (rad("Solid renal mass", severity="urgent"), 41, "urgent"),
    (rad("Ureteral calculus at the UVJ", answers_indication=True), 52, "soon"),
    (rad("Bronchial wall thickening", severity="info", answers_indication=True), 58, "none"),
    (rad("Stable solid pulmonary nodule, Lung-RADS 2", answers_indication=True), 66, "watch"),
    (rad("Extra-axial lesion, likely meningioma", size_mm=14), 76, "watch"),
    (rad("Simple renal cyst", size_mm=21), 69, "none"),
    (rad("Hepatic hypodensity, too small to characterize", size_mm=5), 47, "none"),
    (rad("Small vessel ischemic change", severity="info"), 76, "watch"),
    (rad("Dilated ascending aorta", size_mm=44), 47, "soon"),
])
def test_radiology_triage_rules(finding, age, expected):
    assert radiology_triage(finding, age) == expected


def test_lab_triage_rules():
    history, lab, _ = inputs("case_010")
    by = {r.analyte: r for r in lab.rows}
    f = lambda name: next(x for x in lab.findings if x.label == name)          # noqa: E731
    today = date(2026, 10, 23)
    assert lab_triage(f("Hemoglobin A1c"), by["Hemoglobin A1c"], history, today) == "soon"   # 6.8%
    assert lab_triage(f("LDL Cholesterol"), by["LDL Cholesterol"], history, today) == "watch"
    h5, lab5, _ = inputs("case_005")
    by5 = {r.analyte: r for r in lab5.rows}
    g = lambda name: next(x for x in lab5.findings if x.label == name)         # noqa: E731
    assert lab_triage(g("Sodium"), by5["Sodium"], h5, today) == "soon"
    assert lab_triage(g("Hemoglobin"), by5["Hemoglobin"], h5, today) == "soon"   # low
    assert lab_triage(g("eGFR"), by5["eGFR"], h5, today) == "watch"
    old = g("Sodium").model_copy(update={"observed_at": "2025-01-01"})
    assert lab_triage(old, by5["Sodium"], h5, today) == "watch"
    h4, lab4, _ = inputs("case_004")
    flu = next(x for x in lab4.findings if x.label == "Influenza A")
    assert lab_triage(flu, None, h4, today) == "none"


def test_model_critic_disputes_are_noted_not_deleted(monkeypatch):
    history, lab, rad_ = inputs("case_001")
    first = build_case_record(history, lab, rad_).findings[0]
    monkeypatch.setattr(summarize_agent, "_critic", lambda *a: CriticReport(
        disputed=[Dispute(finding_id=first.id, reason="size not in source"),
                  Dispute(finding_id="ghost", reason="x")], summary="Plain summary."))
    r = run_summarize(history, lab, rad_, use_llm=True)
    disputed = next(f for f in r.findings if f.id == first.id)
    assert disputed.confidence == round(first.confidence * 0.5, 2) and r.summary == "Plain summary."
    assert len(r.findings) == len(build_case_record(history, lab, rad_).findings)
    assert not any("ghost" in n for n in r.critic_notes)


def test_model_critic_failure_keeps_record(monkeypatch):
    def boom(*a):
        raise RuntimeError("ThrottlingException")
    monkeypatch.setattr(summarize_agent, "_critic", boom)
    r = run_summarize(*inputs("case_001"), use_llm=True)
    assert r.findings and any("unavailable" in n for n in r.critic_notes)


def test_next_steps_request_mapping():
    r = build_case_record(*inputs("case_001"))
    req = to_next_steps_request(r, {"class": [{"value": "BLUEBONNET-PPO-500"}]}, PatientContext(zip="78745"))
    assert [f.id for f in req.findings] == [f.id for f in r.findings]
    assert all(f.triage == r.triage[f.id] for f in req.findings)
