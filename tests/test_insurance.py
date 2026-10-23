"""Insurance Agent: coverage profiles for every case, cost checks, tools, and LLM failure handling. No AWS."""

import json
from pathlib import Path

import pytest

from carerelay import insurance
from carerelay.insurance import agent as insurance_agent
from carerelay.insurance.agent import make_insurance_tools

CASES = Path(__file__).resolve().parents[1] / "data" / "cases"


def coverage(case_id: str) -> dict:
    return json.loads((CASES / f"{case_id}.json").read_text())["Coverage"]


@pytest.mark.parametrize("case_id", [p.stem for p in sorted(CASES.glob("case_*.json"))])
def test_profile_for_every_case(case_id):
    p = insurance.coverage_profile(coverage(case_id))
    assert p.plan_id == coverage(case_id)["class"][0]["value"]
    assert p.notes == []                                   # every bundled member is in the payer lookup
    assert 0 <= p.deductible_remaining <= p.deductible and 0 <= p.oop_remaining <= p.oop_max


def test_ppo_accumulators_and_rules():
    p = insurance.coverage_profile(coverage("case_001"))   # Bluebonnet PPO, $120 of $500 met
    assert p.deductible_remaining == 380 and p.oop_remaining == 3690
    assert p.referral_required_for == [] and p.out_of_network_covered
    assert insurance.estimate(p, "ct_chest_wo", "IMG-BRIC").patient_pays == 388.0


def test_hmo_requires_referral_and_no_oon():
    p = insurance.coverage_profile(coverage("case_002"))   # Lone Star HMO
    assert "office_specialist" in p.referral_required_for and not p.out_of_network_covered
    check = insurance.estimate(p, "visit_urology", "URO-LSU")
    assert check.in_network and check.referral_required


def test_unknown_member_is_noted_not_fatal():
    p = insurance.coverage_profile({"class": [{"value": "CEDAR-HDHP-3500"}], "subscriberId": "NOPE-1"})
    assert p.deductible_met == 0 and "not found" in p.notes[0]
    with pytest.raises(ValueError):
        insurance.coverage_profile({"subscriberId": "x"})


def test_tools_are_bound_to_the_patient():
    p = insurance.coverage_profile(coverage("case_009"))
    summary, network, cost = make_insurance_tools(p)
    assert "member_id" not in summary() and summary()["plan_id"] == "LONESTAR-HMO-2000"
    assert network(provider_ids=["GYN-WHSA", "IMG-BRIC", "NOPE"]) == {
        "GYN-WHSA": True, "IMG-BRIC": False, "NOPE": "unknown provider"}
    assert cost(service="us_pelvis", provider_id="GYN-WHSA")["in_network"] is True
    assert "error" in cost(service="nope", provider_id="GYN-WHSA")
    for t in (summary, network, cost):
        assert t.tool_spec["description"]


def test_run_without_llm_uses_template():
    p = insurance.run_insurance_agent(coverage("case_005"), use_llm=False)
    assert "Pecan Senior Advantage" in p.summary and "referral" in p.summary


def test_llm_failure_keeps_template(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("AccessDenied")
    monkeypatch.setattr(insurance_agent, "make_insurance_agent", boom)
    p = insurance.run_insurance_agent(coverage("case_007"), use_llm=True)
    assert "Cedar Mutual" in p.summary and any("unavailable" in n for n in p.notes)


def test_strands_model_sends_no_temperature():
    from carerelay.aws import BEDROCK_MODEL_ID, make_strands_model
    config = make_strands_model().get_config()
    assert config["model_id"] == BEDROCK_MODEL_ID and "temperature" not in config
