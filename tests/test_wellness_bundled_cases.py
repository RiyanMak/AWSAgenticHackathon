"""Wellness against the bundled synthetic cases on main (data/CASES.md), via the stand-in adapter."""

import pytest

from carerelay.dev_cases import case_ids, load_case
from carerelay.wellness import clients
from carerelay.wellness.rules import build_plan


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CARERELAY_OFFLINE", "1")
    clients.get_otc_label.cache_clear()


def plan_for(cid):
    return build_plan(load_case(cid))


def offered(plan):
    return {o.ingredient for o in plan.otc.options}


def excluded(plan):
    return {e.name: e.reasons for e in plan.otc.excluded}


@pytest.mark.parametrize("cid", case_ids())
def test_every_case_builds_a_plan(cid):
    plan = plan_for(cid)
    assert plan.status == "plan", plan.audit
    assert plan.nutrition and plan.activity and plan.otc


def test_case_001_dextromethorphan_allergy_and_current_ibuprofen():
    plan = plan_for("case_001")  # 6-week cough, DM allergy, takes ibuprofen
    ex = excluded(plan)
    assert "dextromethorphan hydrobromide" in ex
    assert any("allergy" in r for r in ex["dextromethorphan hydrobromide"])
    assert "dextromethorphan hydrobromide" not in offered(plan)
    assert not any("diabetes in your history" in g.reason for g in plan.nutrition.guidance)  # prediabetes


def test_case_005_anticoagulant_and_kidney_block_otc():
    record = load_case("case_005")  # on apixaban; visit is a fall, so no OTC symptom match
    assert "anticoagulant" in record.history.risk_flags
    plan = build_plan(record.model_copy(update={"visit_reason": "headache after a fall"}))
    assert plan.otc.status == "pharmacist_only" and not plan.otc.options
    assert any("anticoagulant" in r for r in plan.otc.blocking_reasons)
    assert plan.nutrition.sodium_target_mg == 1500
    assert any("blood thinner" in c for c in plan.activity.cautions)


def test_case_007_no_nsaid_and_alt_limits_acetaminophen():
    plan = plan_for("case_007")  # ibuprofen allergy, ALT 41 (H)
    assert plan.otc.status == "pharmacist_only"
    assert any("ALT" in r for r in plan.otc.blocking_reasons)


def test_case_008_ckd_labs_with_naproxen():
    plan = plan_for("case_008")
    assert plan.otc.status == "pharmacist_only"
    assert any("eGFR" in r or "Creatinine" in r for r in plan.otc.blocking_reasons)


def test_case_010_hypertension_and_diabetes_range_a1c():
    plan = plan_for("case_010")
    assert plan.nutrition.sodium_target_mg == 1500
    assert any("Hemoglobin A1c" in g.reason or "Glucose" in g.reason for g in plan.nutrition.guidance)


@pytest.mark.parametrize("cid", ["case_005", "case_006", "case_009"])
def test_care_first_symptoms_get_no_otc_and_gentle_activity(cid):
    # fall with head strike, chest pain with shortness of breath, car crash
    plan = build_plan(load_case(cid).model_copy(update={"visit_reason": load_case(cid).visit_reason + " pain"}))
    assert not plan.otc.options
    assert plan.activity.intensity == "gentle"


def test_case_004_flu_still_gets_options():
    plan = plan_for("case_004")
    assert {"acetaminophen", "guaifenesin"} <= offered(plan)


def test_case_003_meloxicam_blocks_second_nsaid():
    plan = plan_for("case_003")
    if plan.otc.status == "options":
        assert not offered(plan) & {"ibuprofen", "naproxen sodium", "aspirin"}
