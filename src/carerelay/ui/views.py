"""HTML for the Course theme: the agent course (map + task table), handoff log and results.

Pure functions from (agent states, events, report) to HTML strings, so they are easy to test.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from .contracts import AGENTS, next_steps_view, payload, summarize_view

# Positions on the course map (viewBox 0 0 760 300)
POS = {
    "start": (44, 150), "lab": (180, 62), "radiology": (180, 150), "history": (180, 238),
    "summarize": (340, 150), "wellness": (500, 70), "next_steps": (500, 205), "insurance": (640, 258),
    "patient": (700, 110),
}
LEGS = [
    ("start", "lab"), ("start", "radiology"), ("start", "history"),
    ("lab", "summarize"), ("radiology", "summarize"), ("history", "summarize"),
    ("summarize", "wellness"), ("summarize", "next_steps"),
    ("next_steps", "insurance"), ("wellness", "patient"), ("next_steps", "patient"),
]
STATE_LABEL = {
    "waiting": "Waiting", "running": "Working", "ok": "Done", "demo": "Done (demo data)",
    "not_implemented": "Not built yet", "skipped": "Skipped", "needs_clinical_reevaluation": "Needs review",
}
TRIAGE_LABEL = {
    "urgent": "Urgent", "soon": "Book soon", "watch": "Mention to your PCP", "none": "No follow-up needed",
    "expected": "Expected", "answered": "Answers the question",
}
NAMES = {**{a.id: a.name for a in AGENTS}, "patient": "You", "start": "Uploads"}
CHECK = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def agent_states(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold events into {agent: {state, elapsed}}."""
    out = {a.id: {"state": "waiting", "elapsed": None} for a in AGENTS}
    for e in events:
        if e["type"] == "stage_start" and out[e["agent"]]["state"] == "waiting":
            out[e["agent"]]["state"] = "running"
        elif e["type"] == "stage_end":
            out[e["agent"]] = {"state": e["status"], "elapsed": e.get("elapsed_seconds")}
    return out


def _done(state: str) -> bool:
    return state in ("ok", "demo")


# ---------------------------------------------------------------------------- course map


def course_map(states: dict[str, dict[str, Any]], events: list[dict[str, Any]]) -> str:
    active = {(e["from"], e["to"]) for e in events[-3:] if e["type"] == "handoff"}
    reached_patient = any(e["type"] == "handoff" and e["to"] == "patient" for e in events)
    legs = []
    for a, b in LEGS:
        (x1, y1), (x2, y2) = POS[a], POS[b]
        src_done = a == "start" and bool(events) or (a in states and _done(states[a]["state"]))
        cls = "leg run" if src_done else "leg"
        if (a, b) in active or (b, a) in active:
            cls += " live"
        legs.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}"/>')
    sx, sy = POS["start"]
    marks = [f'<path d="M{sx} {sy - 20} L{sx + 18} {sy + 11} L{sx - 18} {sy + 11} Z" class="ctrl run"/>',
             f'<text x="{sx}" y="{sy + 34}" class="ctrl-name" text-anchor="middle">Uploads</text>']
    for i, a in enumerate(AGENTS, start=1):
        x, y = POS[a.id]
        st = states[a.id]["state"]
        cls = {"waiting": "ctrl", "running": "ctrl running", "ok": "ctrl done", "demo": "ctrl done demo",
               "not_implemented": "ctrl unbuilt", "skipped": "ctrl unbuilt"}.get(st, "ctrl error")
        tick = f'<path d="M{x - 6} {y} l4 4 l8 -9" class="tick"/>' if _done(st) else f'<text x="{x}" y="{y + 5}" class="ctrl-num" text-anchor="middle">{i}</text>'
        marks.append(
            f'<g><title>{escape(a.name)}: {escape(a.task)} ({STATE_LABEL.get(st, st)})</title>'
            f'<circle cx="{x}" cy="{y}" r="16" class="{cls}"/>{tick}'
            f'<text x="{x}" y="{y + 34}" class="ctrl-name" text-anchor="middle">{escape(a.name.replace(" Agent", ""))}</text></g>'
        )
    px, py = POS["patient"]
    fin = "ctrl done" if reached_patient else "ctrl"
    marks.append(f'<circle cx="{px}" cy="{py}" r="12" class="{fin}"/><circle cx="{px}" cy="{py}" r="19" class="{fin}"/>'
                 f'<text x="{px}" y="{py + 38}" class="ctrl-name" text-anchor="middle">You</text>')
    contours = "".join(
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" class="contour"/>'
        for cx, cy, rx, ry in [(340, 150, 300, 128), (340, 150, 220, 90), (340, 150, 130, 52), (620, 240, 110, 52), (620, 240, 55, 26)]
    )
    return f'<svg class="course-map" viewBox="0 0 760 300" role="img" aria-label="Agent course">{contours}{"".join(legs)}{"".join(marks)}</svg>'


def task_table(states: dict[str, dict[str, Any]]) -> str:
    rows = ""
    for i, a in enumerate(AGENTS, start=1):
        s = states[a.id]
        el = f'{s["elapsed"]:.1f} s' if s["elapsed"] is not None else ""
        rows += (f'<tr class="st-{s["state"]}"><td class="n">{i}</td><td><b>{escape(a.name)}</b><span>{escape(a.task)}</span></td>'
                 f'<td>{escape(a.produces)}</td><td class="state">{STATE_LABEL.get(s["state"], s["state"])}</td><td class="num">{el}</td></tr>')
    return ('<table class="tasks"><thead><tr><th>#</th><th>Agent and task</th><th>Hands over</th><th>Status</th>'
            f'<th class="num">Time</th></tr></thead><tbody>{rows}</tbody></table>')


def handoff_log(events: list[dict[str, Any]]) -> str:
    hand = [e for e in events if e["type"] == "handoff"]
    if not hand:
        return '<p class="empty">Handoffs between agents appear here as the run goes.</p>'
    t0 = events[0]["t"]
    rows = "".join(
        f'<li><span class="t">+{e["t"] - t0:4.1f} s</span><b>{escape(NAMES[e["from"]])}</b>'
        f'<span class="arrow" aria-hidden="true">→</span><b>{escape(NAMES[e["to"]])}</b><span class="what">{escape(e["what"])}</span></li>'
        for e in reversed(hand)  # newest first, so the live handoff is always in view
    )
    return f'<ol class="handoffs">{rows}</ol>'


# ------------------------------------------------------------------------------- results


def _when(iso: str) -> tuple[str, str]:
    d = datetime.fromisoformat(iso)
    return d.strftime("%a %b %-d"), d.strftime("%-I:%M %p")


def results(report: dict[str, Any], confirmed: bool, button: str = "") -> str:
    """Result panel. ``button`` is the confirm/undo control's HTML, placed under the appointments."""
    st = report["stages"]
    if st.get("summarize", {}).get("status") not in ("ok", "demo"):
        reason = st.get("summarize", {}).get("reason") or st.get("summarize", {}).get("error") or ""
        return f'<p class="empty">Results appear when Summarize has run. {escape(reason)}</p>'
    s = summarize_view(st["summarize"]).model_dump()
    demo_note = '<p class="demo-note">Some agents are not built yet; their parts of this result use demo data from the synthetic case.</p>' if any(v.get("status") == "demo" for v in st.values()) else ""
    ledger = "".join(
        f'<li class="tr-{i["triage"]}"><span class="sym" aria-hidden="true"></span><div><b>{escape(i["title"])}</b>'
        f'<span class="tri">{TRIAGE_LABEL[i["triage"]]}{" · only in FINDINGS" if i.get("in_impression") is False else ""}</span>'
        f'<p>{escape(i["plain"])}</p><span class="owner">Owner: {escape(i["owner"])}</span></div></li>'
        for i in s["items"]
    )
    ns = next_steps_view(st.get("next_steps", {})).model_dump() if st.get("next_steps", {}).get("status") in ("ok", "demo") else {}
    appts = ""
    for k, a in enumerate(ns.get("appointments", []), start=1):
        day, time_ = _when(a["start"])
        flags = " · referral needed" * a["referral_required"] + " · prior auth" * a["prior_auth_required"]
        appts += (f'<tr class="{"punched" if confirmed else ""}"><td class="n">{k}</td><td><b>{escape(a["service_name"])}</b>'
                  f'<span>{escape(a["provider_name"])}{", " + escape(a["clinician"]) if a.get("clinician") else ""}{flags}</span></td>'
                  f'<td>{day}<span>{time_}</span></td><td class="num">{a["miles"]} mi</td><td class="num">${a["patient_pays"]:,.0f}</td>'
                  f'<td class="p">{CHECK if confirmed else ""}</td></tr>')
    total = f'${ns.get("total_patient_pays", 0):,.0f}'
    plan = payload("wellness", st.get("wellness", {}))
    tips = ""
    if plan.get("status") == "seek_care":
        tips = f'<li class="out"><b>Seek care</b> {escape(plan.get("seek_care_message") or "")}</li>'
    for g in (plan.get("nutrition") or {}).get("guidance", []):
        tips += f'<li><b>Nutrition</b> {escape(g["text"])}</li>'
    if plan.get("activity"):
        tips += f'<li><b>Activity</b> {escape(plan["activity"]["weekly_target"])}</li>'
    otc = plan.get("otc") or {}
    for o in otc.get("options", []):
        tips += f'<li><b>OTC</b> {escape(o["ingredient"])}{" (" + escape(o["purpose"]) + ")" if o.get("purpose") else ""}</li>'
    for x in otc.get("excluded", []):
        tips += (f'<li class="out"><b>OTC</b> <span class="txt">{escape(x["name"])}</span>'
                 f'<em>Ruled out: {escape("; ".join(x["reasons"]))}</em></li>')
    status = "Confirmed. Nothing else is booked without you." if confirmed else "Proposed. Nothing is booked until you confirm."
    return f"""
    <section class="headline"><h2>{escape(s["headline"])}</h2>{demo_note}</section>
    <div class="res-grid">
      <section><h3>What the reports found</h3><ul class="ledger">{ledger}</ul></section>
      <section><h3>Your course</h3>
        <table class="controls"><thead><tr><th>#</th><th>Appointment</th><th>When</th><th class="num">Dist.</th><th class="num">You pay</th><th></th></tr></thead>
        <tbody>{appts}</tbody></table>
        <p class="total"><b>{total}</b> estimated · {status}</p>{button}
        <h3>While you wait</h3><ul class="tips">{tips}</ul>
      </section>
    </div>"""
