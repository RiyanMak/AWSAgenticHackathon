"""UI layer: contracts, demo fill, pipeline events and views, offline (no AWS, no browser)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from carerelay import service
from carerelay.ui import contracts, pipeline, views

ROOT = Path(__file__).resolve().parents[1]
CASES = [s["case_id"] for s in service.list_scenarios()]


def _run(case_id: str):
    events: list[dict] = []
    report = pipeline.run({"scenario": case_id, "options": {"llm": False}}, events.append, pace=0)
    return report, events


def test_tokens_generated_files_are_current():
    out = subprocess.run([sys.executable, str(ROOT / "design" / "build_tokens.py"), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


def test_service_emits_stage_events():
    events: list[dict] = []
    service.handle({"scenario": "case_001", "options": {"llm": False}}, on_event=events.append)
    ends = {e["stage"]: e["status"] for e in events if e["type"] == "stage_end"}
    assert set(ends) == set(service.STAGES) and ends["history"] == "ok"


@pytest.mark.parametrize("case_id", CASES)
def test_demo_fill_matches_contracts(case_id):
    report, events = _run(case_id)
    stages = report["stages"]
    for name in ("summarize", "wellness", "next_steps"):
        assert stages[name]["status"] in ("ok", "demo", "skipped", "awaiting_confirmation"), (name, stages[name])
    if stages["summarize"]["status"] in ("ok", "demo"):
        contracts.summarize_view(stages["summarize"])
    if stages["wellness"]["status"] in ("ok", "demo"):
        contracts.WellnessView.model_validate(contracts.payload("wellness", stages["wellness"]))
    if stages["next_steps"]["status"] in ("ok", "demo"):
        contracts.next_steps_view(stages["next_steps"])
    for name in ("lab", "radiology"):
        assert stages[name]["status"] in ("ok", "demo")
        for f in contracts.payload(name, stages[name]).get("findings", []):
            contracts.FindingView.model_validate(f)
    states = views.agent_states(events)
    assert states["history"]["state"] == "ok" and states["summarize"]["state"] != "waiting", states


def test_every_appointment_was_checked_by_insurance():
    report, events = _run("case_001")
    ns = contracts.next_steps_view(report["stages"]["next_steps"])
    accepted = {(c.service, c.provider_id) for c in ns.insurance_checks if c.verdict == "accepted"}
    assert ns.appointments and all((a.service, a.provider_id) in accepted for a in ns.appointments)
    assert all(a.status == "proposed" for a in ns.appointments)  # human confirms
    assert any(e["type"] == "handoff" and e["from"] == "insurance" for e in events)


def test_negative_control_proposes_nothing():
    report, _ = _run("case_004")
    ns = report["stages"]["next_steps"]
    assert ns["status"] != "ok" or contracts.next_steps_view(ns).appointments == []


def test_wellness_uses_history_allergy():
    report, _ = _run("case_001")
    plan = contracts.payload("wellness", report["stages"]["wellness"])
    assert any("dextromethorphan" in " ".join(x["reasons"]) for x in plan["otc"]["excluded"])


def test_all_agents_run_for_real_on_case_001():
    events: list[dict] = []
    pipeline.run({"scenario": "case_001", "options": {"llm": False}}, events.append, demo_fill=False, pace=0)
    states = views.agent_states(events)
    assert all(states[a]["state"] == "ok" for a in ("history", "lab", "radiology", "summarize", "wellness", "next_steps", "insurance")), states


def test_handoffs_stream_while_the_run_is_in_flight():
    events: list[dict] = []
    pipeline.run({"scenario": "case_001", "options": {"llm": False}}, events.append, demo_fill=False, pace=0)
    kinds = [(e["type"], e.get("agent"), e.get("from")) for e in events]
    # History's handoff arrives before Summarize starts, not in a batch after every agent is done
    first_history_handoff = kinds.index(("handoff", None, "history"))
    summarize_start = kinds.index(("stage_start", "summarize", None))
    assert first_history_handoff < summarize_start, kinds
    # No stage is narrated twice
    pairs = [(e["from"], e["to"]) for e in events if e["type"] == "handoff" and e["from"] != "insurance"
             and not (e["from"] == "next_steps" and e["to"] == "insurance")]
    assert len(pairs) == len(set(pairs)), pairs
    assert all("output" not in e for e in events)


def test_views_render():
    report, events = _run("case_001")
    states = views.agent_states(events)
    assert "<svg" in views.course_map(states, events)
    assert "Insurance Agent" in views.task_table(states)
    assert "Insurance Agent" in views.handoff_log(events) or "Insurance" in views.handoff_log(events)
    html = views.results(report, confirmed=False)
    assert "Nothing is booked until you confirm" in html and "Ruled out" in html


def test_app_imports():
    pytest.importorskip("shiny")
    from carerelay.ui import app  # noqa: F401
