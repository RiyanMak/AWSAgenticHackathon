"""Wellness safety cases from SAFETY.md section 5 (eval idea 4) and the OTC rules in section 2.

Runs offline against the bundled openFDA snapshot.
"""

import json
from pathlib import Path

import pytest

from carerelay.schemas import CaseRecord, CodedItem, Finding, HistoryProfile
from carerelay.wellness import clients
from carerelay.wellness.agent import check_narrative, render_plan_text, run_wellness
from carerelay.wellness.rules import build_plan

DEMO = Path(__file__).resolve().parents[1] / "examples" / "wellness_demo_case.json"

FOODS = {"foods": {
    "dried lentils": {"fdc_id": 1, "description": "Lentils, raw", "data_type": "SR Legacy",
                      "per_100g": {"potassium_mg": 677.0, "sodium_mg": 6.0}},
    "brown rice": {"fdc_id": 2, "description": "Rice, brown", "data_type": "SR Legacy",
                   "per_100g": {"potassium_mg": 250.0, "sodium_mg": 4.0}},
}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CARERELAY_OFFLINE", "1")
    clients.get_otc_label.cache_clear()
    monkeypatch.setattr("carerelay.wellness.rules.food_snapshot", lambda: FOODS)


def case(**kw) -> CaseRecord:
    hist = kw.pop("history", {})
    return CaseRecord(
        visit_reason=kw.pop("visit_reason", "headache"),
        patient_age=kw.pop("patient_age", 40),
        findings=kw.pop("findings", []),
        history=HistoryProfile(source=hist.pop("source", "fhir"), **hist),
        **kw,
    )


def lab(label, severity="follow_up", fid=None):
    return Finding(id=fid or f"lab-{label}", source="lab", label=label, value="x", evidence="p1",
                   confidence=0.9, severity=severity, incidental=True)


def offered(plan):
    return {o.ingredient for o in plan.otc.options}


def excluded(plan):
    return {e.name: e.reasons for e in plan.otc.excluded}


def test_baseline_offers_label_grounded_options():
    plan = build_plan(case())
    assert plan.status == "plan"
    assert {"acetaminophen", "ibuprofen"} <= offered(plan)
    for o in plan.otc.options:
        assert o.directions_from_label  # quoted from label, never generated
        assert o.provenance == "openFDA snapshot"


@pytest.mark.parametrize("flag", ["ckd", "pregnancy", "anticoagulant", "liver"])
def test_risk_flags_block_all_otc(flag):
    plan = build_plan(case(history={"risk_flags": [flag]}))
    assert plan.otc.status == "pharmacist_only"
    assert plan.otc.options == []


@pytest.mark.parametrize("label", ["Creatinine", "eGFR", "ALT"])
def test_kidney_or_liver_lab_blocks_all_otc(label):
    plan = build_plan(case(findings=[lab(label)]))
    assert plan.otc.status == "pharmacist_only"


def test_potassium_blocks_nsaids_only():
    plan = build_plan(case(findings=[lab("Potassium")]))
    assert "acetaminophen" in offered(plan)
    assert not offered(plan) & {"ibuprofen", "naproxen sodium", "aspirin"}


def test_aspirin_allergy_excludes_salicylates_and_lists_them():
    plan = build_plan(case(history={"allergies": [CodedItem(display="Aspirin", detail="hives")]}))
    ex = excluded(plan)
    assert "aspirin" in ex and "aspirin" not in offered(plan)
    assert "ibuprofen" in ex  # cross-reactivity: label warns "especially in people allergic to aspirin"
    assert "acetaminophen" in offered(plan)


def test_current_nsaid_is_not_duplicated():
    plan = build_plan(case(history={"medications": [CodedItem(display="naproxen 500 MG", status="active")]}))
    assert "ibuprofen" in excluded(plan)


def test_label_interaction_text_excludes_option():
    plan = build_plan(case(history={"medications": [CodedItem(display="furosemide 20 MG", status="active")]}))
    assert any("diuretic" in r for r in excluded(plan)["ibuprofen"])


def test_unknown_or_minor_age_blocks():
    assert build_plan(case(patient_age=None)).otc.status == "pharmacist_only"
    assert build_plan(case(patient_age=12)).otc.status == "pharmacist_only"


def test_degraded_history_blocks_otc():
    assert build_plan(case(history={"source": "degraded"})).otc.status == "pharmacist_only"


def test_no_symptom_match_means_no_otc():
    assert build_plan(case(visit_reason="routine checkup")).otc.status == "not_applicable"


def test_red_flag_replaces_plan_even_after_confirmation():
    for confirmed in (False, True):
        plan = build_plan(case(findings=[lab("Potassium", "red_flag")], human_confirmed=confirmed))
        assert plan.status == "seek_care" and plan.otc is None


def test_urgent_waits_for_confirmation():
    assert build_plan(case(findings=[lab("Glucose", "urgent")])).status == "seek_care"
    plan = build_plan(case(findings=[lab("Glucose", "urgent")], human_confirmed=True))
    assert plan.status == "plan" and plan.seek_care_message


def test_hypertension_lowers_sodium_target():
    assert build_plan(case()).nutrition.sodium_target_mg == 2300
    plan = build_plan(case(history={"risk_flags": ["hypertension"]}))
    assert plan.nutrition.sodium_target_mg == 1500


def test_potassium_caution_excludes_high_potassium_and_unknown_foods():
    plan = build_plan(case(history={"risk_flags": ["ckd"]}))
    names = {f.name for f in plan.nutrition.foods}
    assert names == {"brown rice"}  # lentils too high, others have no data
    assert any(e.name == "dried lentils" for e in plan.nutrition.excluded_foods)


def test_food_allergy_filter():
    plan = build_plan(case(history={"allergies": [CodedItem(display="Peanut")]}))
    assert "peanut butter, no salt added" in {e.name for e in plan.nutrition.excluded_foods}


def test_cardiopulmonary_finding_gives_gentle_activity():
    f = Finding(id="r1", source="radiology", label="Cardiomegaly", value="0.8", evidence="img",
                confidence=0.8, severity="follow_up", incidental=True)
    assert build_plan(case(findings=[f])).activity.intensity == "gentle"


def test_demo_case_story():
    plan = build_plan(CaseRecord.model_validate(json.loads(DEMO.read_text())))
    assert plan.status == "plan"
    assert offered(plan) == {"acetaminophen"}
    assert "aspirin" in excluded(plan)
    assert plan.nutrition.sodium_target_mg == 1500


def test_incidental_glucose_shapes_nutrition():
    plan = build_plan(case(findings=[lab("Glucose")]))
    assert any("Glucose" in g.reason for g in plan.nutrition.guidance)


def test_condition_reason_not_duplicated_by_risk_flag():
    plan = build_plan(case(history={
        "conditions": [CodedItem(display="Essential hypertension")], "risk_flags": ["hypertension"]}))
    reasons = excluded(plan)["ibuprofen"]
    assert sum("high blood pressure" in r for r in reasons) == 1


def test_prediabetes_is_not_called_diabetes():
    plan = build_plan(case(history={"conditions": [CodedItem(display="Prediabetes")]}))
    assert not any("diabetes in your history" in g.reason for g in plan.nutrition.guidance)


def test_narrative_check_rejects_unlisted_drug():
    plan = build_plan(case(history={"risk_flags": ["ckd"]}))
    assert check_narrative(plan, plan.banner + " Try Advil.")
    assert not check_narrative(plan, render_plan_text(plan))


def test_run_wellness_without_model_uses_template():
    out = run_wellness(case(), use_model=False)
    assert out["narrator"] == "template" and "Not medical advice" in out["text"]
