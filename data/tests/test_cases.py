"""Integrity checks: every case is internally consistent and schedulable in the mock network."""

import json

import pytest

import build
import labs
import network

CASES = build.load_cases()
TRIAGE = {"urgent", "soon", "watch", "none"}


def test_ten_cases():
    assert len(CASES) == 10
    assert len({c["case_id"] for c in CASES}) == 10


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_case_consistency(case):
    plan_id = case["Coverage"]["class"][0]["value"]
    network.get_plan(plan_id)
    assert network.get_member(case["Coverage"]["subscriberId"])["plan_id"] == plan_id
    network.distance_miles(case["Patient"]["address"][0]["postalCode"], "78701")
    for order in case["labs"]:
        labs.facility(order["lab"])
        for panel in order["panels"]:
            labs.expand_panel(panel, case["Patient"]["gender"])
    for item in case["answer_key"]:
        assert item["triage"] in TRIAGE
        assert item["source"] in {"radiology", "lab", "intake"}
        if item["triage"] in {"urgent", "soon"}:
            assert item["followup_services"], f"{item['finding']}: actionable but no services"
        if item["triage"] == "none":
            assert not item["followup_services"], f"{item['finding']}: 'none' but has services"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_followups_schedulable_in_network(case):
    plan_id = case["Coverage"]["class"][0]["value"]
    zip_code = case["Patient"]["address"][0]["postalCode"]
    radius = case["intake"]["max_travel_miles"]
    services = {s for item in case["answer_key"] for s in item["followup_services"]}
    for svc in services:
        options = network.find_providers(svc, plan_id, zip_code, max_miles=radius, in_network_only=True)
        assert options, f"{case['case_id']}: no in-network {svc} within {radius} mi of {zip_code}"
        assert network.find_slots(options[0]["provider_id"], svc, "2026-10-23", days=60,
                                  availability=case["intake"]["availability"]), f"{svc}: no slots"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_intake_expected_hides_answer_key(case):
    out = json.dumps(build.intake_expected(case))
    assert "answer_key" not in out and '"_' not in out
