"""Run the pipeline for the UI and narrate it as agent events and handoffs.

``run(request, emit)`` calls ``service.handle(request, on_event=...)``. Real agents report through
that callback; for any stage still ``not_implemented`` it optionally fills in demo output
(``demo.py``) at a readable pace, so the agent course and handoff log play end to end.

Event types (all dicts with ``t`` in unix seconds):
  stage_start {agent}
  stage_end   {agent, status, elapsed_seconds}
  handoff     {from, to, what}
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .. import service
from . import demo
from .contracts import AGENT, PARALLEL_FIRST, next_steps_view, payload, summarize_view

Emit = Callable[[dict[str, Any]], None]
UNBUILT = "not_implemented"


def _ev(emit: Emit, kind: str, **fields: Any) -> None:
    emit({"type": kind, "t": time.time(), **fields})


# --------------------------------------------------------------------- handoff descriptions


def describe(stage: str, stage_dict: dict[str, Any], to: str) -> str:
    """One line saying what an agent handed to the next one."""
    out = payload(stage, stage_dict)
    if stage == "history":
        p = out
        flags = ", ".join(p.get("risk_flags", [])) or "none"
        return (f"HistoryProfile: {len(p.get('conditions', []))} conditions, {len(p.get('medications', []))} meds, "
                f"{len(p.get('allergies', []))} allergies; risk flags: {flags}")
    if stage in ("lab", "radiology"):
        fs = out.get("findings", [])
        flagged = sum(f.get("severity") != "info" for f in fs)
        extra = ""
        if stage == "radiology":
            only = sum(f.get("in_impression") is False for f in fs)
            extra = f", {only} only in FINDINGS" if only else ""
        return f"{AGENT[stage].produces}: {len(fs)} findings, {flagged} flagged{extra}"
    if stage == "summarize":
        items = [i.model_dump() for i in summarize_view(stage_dict).items]
        inc = sum(i.get("incidental") for i in items)
        act = sum(i.get("triage") in ("urgent", "soon") for i in items)
        return f"Incidental ledger: {inc} incidental, {act} need a follow-up"
    if stage == "wellness":
        otc = out.get("otc") or {}
        return f"WellnessPlan: {len(otc.get('options', []))} OTC options, {len(otc.get('excluded', []))} ruled out"
    if stage == "next_steps" and to == "patient":
        v = next_steps_view(stage_dict)
        return f"{len(v.appointments)} proposed appointments, ${v.total_patient_pays:,.0f} estimated"
    return AGENT[stage].produces


def _handoffs(emit: Emit, stage: str, stage_dict: dict[str, Any]) -> None:
    for to in AGENT[stage].hands_to:
        if stage == "next_steps" and to == "insurance":
            continue  # the propose/check loop is narrated separately
        _ev(emit, "handoff", **{"from": stage, "to": to, "what": describe(stage, stage_dict, to)})


def _insurance_loop(emit: Emit, checks, pace: float, status: str = "ok") -> None:
    """Narrate each Next Steps -> Insurance proposal and its verdict."""
    t0 = time.time()
    for chk in checks:
        _ev(emit, "stage_start", agent="insurance")
        _ev(emit, "handoff", **{"from": "next_steps", "to": "insurance",
                                "what": f"Propose {chk.service.replace('_', ' ')} at {chk.provider_name} ({chk.miles} mi)"})
        time.sleep(pace / 3)
        _ev(emit, "handoff", **{"from": "insurance", "to": "next_steps", "what": f"{chk.verdict.capitalize()}: {chk.note}"})
    if checks:
        _ev(emit, "stage_end", agent="insurance", status=status, elapsed_seconds=round(time.time() - t0, 2))


# -------------------------------------------------------------------------------------- run


def run(request: dict[str, Any], emit: Emit, demo_fill: bool = True, pace: float = 0.6) -> dict[str, Any]:
    """Return the service report, with unbuilt stages filled by demo output when ``demo_fill``."""
    case_id = request.get("scenario")
    fill = demo_fill and bool(case_id)  # demo needs a bundled case's answer key

    def relay(event: dict[str, Any]) -> None:
        # Pass real agent progress through; hold back "not built" ends we are about to fill.
        if fill and event.get("status") == UNBUILT:
            return
        _ev(emit, event["type"], agent=event["stage"], **{k: v for k, v in event.items() if k not in ("type", "stage", "t")})

    report = service.handle(request, on_event=relay)
    stages = report["stages"]
    if not fill or not any(st["status"] == UNBUILT for st in stages.values()):
        for name in ("lab", "radiology", "history", "summarize", "wellness"):
            if stages[name]["status"] == "ok":
                _handoffs(emit, name, stages[name])
        if stages["next_steps"]["status"] == "ok":
            _insurance_loop(emit, next_steps_view(stages["next_steps"]).insurance_checks, pace=0)
            _handoffs(emit, "next_steps", stages["next_steps"])
        return report

    case = demo.load_case(case_id)

    def finish(name: str, payload: dict[str, Any], started: float) -> None:
        stages[name] = {"status": "demo", "demo": True, **payload}
        _ev(emit, "stage_end", agent=name, status="demo", elapsed_seconds=round(time.time() - started, 2))

    # Stage 1: Lab, Radiology and History ran inside service.handle; demo only fills a stage still unbuilt
    t0 = time.time()
    time.sleep(pace)
    for name in ("lab", "radiology"):
        if stages[name]["status"] == UNBUILT:
            finish(name, demo.findings(case, name), t0)
    for name in PARALLEL_FIRST:
        if stages[name]["status"] in ("ok", "demo"):
            _handoffs(emit, name, stages[name])

    # Stage 2: Summarize
    if stages["summarize"]["status"] == UNBUILT:
        t0 = time.time()
        _ev(emit, "stage_start", agent="summarize")
        time.sleep(pace)
        finish("summarize", demo.summarize(case).model_dump(), t0)
    summary = summarize_view(stages["summarize"])
    _handoffs(emit, "summarize", stages["summarize"])

    # Stage 3: Wellness and Next Steps (with the Insurance loop)
    profile = stages["history"].get("profile") if stages["history"]["status"] == "ok" else None
    if stages["wellness"]["status"] == UNBUILT:
        t0 = time.time()
        _ev(emit, "stage_start", agent="wellness")
        finish("wellness", demo.wellness(profile), t0)
    if stages["next_steps"]["status"] == UNBUILT:
        t0 = time.time()
        _ev(emit, "stage_start", agent="next_steps")
        plan = demo.next_steps(case, summary)
        _insurance_loop(emit, plan.insurance_checks, pace, status="demo")
        finish("next_steps", plan.model_dump(), t0)
    _handoffs(emit, "wellness", stages["wellness"])
    _handoffs(emit, "next_steps", stages["next_steps"])
    return report
