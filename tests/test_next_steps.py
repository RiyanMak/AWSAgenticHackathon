"""Next Steps: plan invariants on every case, service choice vs answer keys, and the LLM guardrails. No AWS."""

from datetime import date, datetime, timedelta

import pytest

from carerelay.insurance import agent as insurance_agent
from carerelay.network import net
from carerelay.next_steps import agent as ns_agent
from carerelay.next_steps import plan_followups, run_next_steps
from carerelay.next_steps.agent import make_next_steps_tools
from carerelay.next_steps.catalog import DUE_DAYS
from carerelay.next_steps.demo import load_case, request_from_case
from carerelay.next_steps.planner import ORDER_NEEDED, TRAVEL_BUFFER
from carerelay.next_steps.schema import NextStepsDecision, RoutedFinding, ServiceChoice
from carerelay.insurance import coverage_profile

CASE_IDS = [f"case_{i:03d}" for i in range(1, 11)]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def plan_for(case_id, request=None):
    request = request or request_from_case(load_case(case_id))
    return request, plan_followups(request, coverage_profile(request.coverage))


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_plan_invariants(case_id):
    request, plan = plan_for(case_id)
    cov = plan.coverage
    avail = request.patient.availability or {}
    proposed = [s for s in plan.steps if s.status == "proposed"]
    for s in proposed:
        prov = net().get_provider(s.provider_id)
        assert s.service in prov["services"]
        assert s.in_network or cov.out_of_network_covered
        start = datetime.fromisoformat(s.slot_start)
        assert WEEKDAYS[start.weekday()] in avail.get("days", WEEKDAYS)
        if avail.get("times") == "morning":
            assert start.hour < 12
        if avail.get("times") == "afternoon":
            assert start.hour >= 12
        if not any("earliest after" in n for n in s.notes):
            assert start.date() <= date.fromisoformat(s.due_by)
        assert s.appointment["status"] == "proposed" and s.patient_pays is not None
        assert prov["accepting_new_patients"] or s.established
    # no two proposals overlap, travel buffer included
    spans = sorted((datetime.fromisoformat(s.slot_start), datetime.fromisoformat(s.slot_end)) for s in proposed)
    for (_, end), (nxt, _) in zip(spans, spans[1:]):
        assert end + TRAVEL_BUFFER <= nxt
    # referrals and orders come from the PCP visit, so it is first when present
    pcp = next((s for s in proposed if s.service == "visit_primary_care"), None)
    for s in proposed:
        if pcp and s is not pcp and (s.referral_required or net().get_service(s.service)["category"] in ORDER_NEEDED) \
                and s.triage != "urgent":
            assert s.slot_start > pcp.slot_start
    assert plan.total_patient_pays == round(sum(s.patient_pays for s in proposed), 2)
    # triage "none" findings never produce steps
    none_ids = {f.id for f in request.findings if f.triage == "none"}
    assert not any(set(s.finding_ids) & none_ids for s in plan.steps)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_actionable_answer_key_services_are_planned(case_id):
    case = load_case(case_id)
    _, plan = plan_for(case_id)
    planned = {s.service for s in plan.steps}
    for a in case["answer_key"]:
        if a["triage"] in ("urgent", "soon"):
            assert set(a["followup_services"]) <= planned, a["finding"]


def test_negative_control_has_no_steps():
    _, plan = plan_for("case_004")
    assert plan.steps == [] and "No follow-up" in plan.summary


def test_established_pcp_used_even_when_closed_to_new_patients():
    _, plan = plan_for("case_010")      # PCP-NWAPC is not accepting new patients, but he is established
    pcp = next(s for s in plan.steps if s.service == "visit_primary_care")
    assert pcp.provider_id == "PCP-NWAPC" and pcp.established


def test_spanish_speaker_gets_spanish_speaking_providers():
    _, plan = plan_for("case_009")
    assert all(s.language_match for s in plan.steps if s.status == "proposed")


def test_hmo_referral_visit_comes_first_and_no_out_of_network():
    _, plan = plan_for("case_002")
    steps = {s.service: s for s in plan.steps}
    assert steps["visit_urology"].referral_required and steps["visit_endocrinology"].referral_required
    assert any("Referral for" in r for r in steps["visit_primary_care"].reasons)
    assert steps["visit_primary_care"].slot_start < steps["visit_urology"].slot_start
    assert all(s.in_network for s in plan.steps if s.status == "proposed")


def test_specialist_follows_the_scan_for_the_same_finding():
    _, plan = plan_for("case_001")
    steps = {s.service: s for s in plan.steps}
    assert steps["ct_chest_wo"].slot_start < steps["visit_pulmonology"].slot_start
    assert steps["us_thyroid"].slot_start < steps["visit_endocrinology"].slot_start


def test_urgent_items_within_two_weeks():
    _, plan = plan_for("case_007")      # solid renal mass
    for s in plan.steps:
        if s.triage == "urgent":
            assert s.status == "proposed"
            assert datetime.fromisoformat(s.slot_start).date() <= date(2026, 10, 23) + timedelta(days=DUE_DAYS["urgent"])


def test_costs_accumulate_in_date_order():
    _, plan = plan_for("case_001")      # PPO with $380 deductible left
    steps = {s.service: s for s in plan.steps}
    ct, us = steps["ct_chest_wo"], steps["us_thyroid"]
    assert ct.slot_start < us.slot_start
    assert ct.patient_pays == 388.0                         # $380 deductible + 20% of the rest
    assert us.patient_pays == round(us.allowed_amount * 0.2, 2)   # deductible already met by the CT
    _, hdhp = plan_for("case_007")
    assert hdhp.total_patient_pays <= hdhp.coverage.oop_remaining


def test_radius_widens_then_reports_no_option():
    request = request_from_case(load_case("case_008"))   # Georgetown, far from most specialists
    request.patient.max_travel_miles = 3
    _, plan = plan_for("case_008", request)
    widened = [s for s in plan.steps if s.search_rounds > 1]
    assert widened and all("widened" in " ".join(s.notes) or s.status == "no_option_found" for s in widened)

    request.patient.availability = {"days": ["sun"], "times": "any"}   # nobody is open on Sunday
    _, plan = plan_for("case_008", request)
    assert all(s.status in ("no_option_found", "discuss_with_pcp") for s in plan.steps)
    assert "Could not find" in plan.summary


def test_unmapped_finding_and_unknown_service():
    request = request_from_case(load_case("case_004"))
    request.findings = [
        RoutedFinding(id="x-1", source="radiology", label="Mystery opacity", triage="soon"),
        RoutedFinding(id="x-2", source="lab", label="Something", triage="soon", services=["warp_drive", "pft"]),
    ]
    _, plan = plan_for("case_004", request)
    assert plan.unmapped_findings == ["x-1"]
    assert {s.service for s in plan.steps} == {"visit_primary_care", "pft"}
    assert any("warp_drive" in n for n in plan.notes)


# ---------- LLM layer, with a stubbed model ----------

class FakeAgent:
    def __init__(self, decision=None, exc=None):
        self.decision, self.exc = decision, exc

    def __call__(self, prompt, structured_output_model=None):
        if self.exc:
            raise self.exc
        return type("Result", (), {"structured_output": self.decision})()


@pytest.fixture
def no_insurance_llm(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no Bedrock in tests")
    monkeypatch.setattr(insurance_agent, "make_insurance_agent", boom)


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(ns_agent, "make_next_steps_agent", lambda *a, **k: fake)


def test_llm_choice_is_validated_and_applied(monkeypatch, no_insurance_llm):
    request = request_from_case(load_case("case_001"))
    emphysema = next(f for f in request.findings if "emphysema" in f.label.lower())
    use_fake(monkeypatch, FakeAgent(NextStepsDecision(
        service_choices=[ServiceChoice(finding_id=emphysema.id, services=["pft", "visit_pulmonology", "warp_drive"]),
                         ServiceChoice(finding_id="ghost", services=["pft"])],
        patient_explanation="Start with your primary care visit; nothing is booked until you confirm.",
        caregiver_notes=["Bring the CT report."])))
    plan = run_next_steps(request, use_llm=True)
    assert plan.method == "rules+llm" and plan.summary.startswith("Start with")
    assert any("warp_drive" in n for n in plan.notes) and any("ghost" in n for n in plan.notes)
    assert plan.caregiver_notes == ["Bring the CT report."]


def test_llm_explanation_with_invented_cost_is_dropped(monkeypatch, no_insurance_llm):
    use_fake(monkeypatch, FakeAgent(NextStepsDecision(patient_explanation="This will cost about $12.34 total.")))
    plan = run_next_steps(request_from_case(load_case("case_001")), use_llm=True)
    assert "$12.34" not in plan.summary and any("cost not in the plan" in n for n in plan.notes)


def test_llm_failure_keeps_rules_plan(monkeypatch, no_insurance_llm):
    use_fake(monkeypatch, FakeAgent(exc=RuntimeError("ThrottlingException")))
    plan = run_next_steps(request_from_case(load_case("case_001")), use_llm=True)
    assert plan.method == "rules" and plan.steps and any("unavailable" in n for n in plan.notes)


def test_offline_skips_models_entirely(monkeypatch):
    use_fake(monkeypatch, FakeAgent(exc=AssertionError("must not be called")))
    plan = run_next_steps(request_from_case(load_case("case_003")), use_llm=False)
    assert plan.status == "ok" and plan.method == "rules"


def test_bad_coverage_requests_reevaluation():
    request = request_from_case(load_case("case_001"))
    request.coverage = {"class": [{"value": "NO-SUCH-PLAN"}]}
    plan = run_next_steps(request, use_llm=False)
    assert plan.status == "needs_clinical_reevaluation" and plan.error


def test_tools_and_plan_build_limit():
    request = request_from_case(load_case("case_001"))
    cov = coverage_profile(request.coverage)
    state = {"builds": 0, "last_choices": {}}
    catalog_tool, suggest, build, ask_insurance = make_next_steps_tools(request, cov, state)
    assert "ct_chest_wo" in catalog_tool()
    assert suggest(finding_id=request.findings[1].id)["rule_services"] == ["ct_chest_wo", "visit_pulmonology"]
    assert "error" in suggest(finding_id="nope")
    assert "error" in build(service_choices_json="[1,2]")
    for _ in range(2):
        assert "steps" in build(service_choices_json="{}")
    assert "limit" in build(service_choices_json="{}")["error"]
    for t in (catalog_tool, suggest, build, ask_insurance):
        assert t.tool_spec["description"]
