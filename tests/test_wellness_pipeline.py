"""Wellness inside the full service flow (History, Lab, Radiology -> Summarize -> Wellness), offline."""

import pytest

from carerelay import service
from carerelay.wellness import clients


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("CARERELAY_LIVE_APIS", raising=False)
    clients.get_otc_label.cache_clear()


def wellness(case_id, **options):
    report = service.handle({"scenario": case_id, "options": {"llm": False, **options}})
    return report["stages"]["wellness"]["result"]["plan"]


@pytest.mark.parametrize("case_id", [s["case_id"] for s in service.list_scenarios()])
def test_every_case_gets_a_wellness_plan_from_summarize(case_id):
    report = service.handle({"scenario": case_id, "options": {"llm": False}})
    assert report["stages"]["summarize"]["status"] == "ok"
    w = report["stages"]["wellness"]
    assert w["status"] == "ok" and w["result"]["plan"]["status"] in ("plan", "seek_care")


def test_case_004_never_smoker_keeps_cough_options():
    offered = {o["ingredient"] for o in wellness("case_004")["otc"]["options"]}
    assert {"acetaminophen", "guaifenesin", "dextromethorphan hydrobromide"} <= offered


def test_case_001_dextromethorphan_allergy_from_history_pdf():
    ex = {e["name"]: e["reasons"] for e in wellness("case_001")["otc"]["excluded"]}
    assert any("allergy" in r for r in ex["dextromethorphan hydrobromide"])


def test_case_007_urgent_withholds_plan_until_confirmed():
    assert wellness("case_007")["status"] == "seek_care"
    plan = wellness("case_007", human_confirmed=True)
    assert plan["status"] == "plan" and plan["otc"]["status"] != "options"  # ibuprofen allergy, ALT flag
