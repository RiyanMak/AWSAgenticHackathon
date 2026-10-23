"""HTML for the Course theme: the agent course (map + task table), handoff log and results.

Pure functions from (agent states, events, report) to HTML strings, so they are easy to test.
"""

from __future__ import annotations

import re
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
    "awaiting_confirmation": "Waiting for a clinician",
}
TRIAGE_LABEL = {
    "urgent": "Urgent", "soon": "Book soon", "watch": "Mention to your PCP", "none": "No follow-up needed",
    "expected": "Expected", "answered": "Answers the question",
}
NAMES = {**{a.id: a.name for a in AGENTS}, "patient": "You", "start": "Uploads"}
CHECK = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def agent_states(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold events into {agent: {state, elapsed}}."""
    out = {a.id: {"state": "waiting", "elapsed": None, "started": None} for a in AGENTS}
    for e in events:
        if e.get("agent") not in out:
            continue  # e.g. the "inputs" event
        if e["type"] == "stage_start" and out[e["agent"]]["state"] == "waiting":
            out[e["agent"]].update(state="running", started=e["t"])
        elif e["type"] == "stage_end":
            out[e["agent"]].update(state=e["status"], elapsed=e.get("elapsed_seconds"))
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


def task_table(states: dict[str, dict[str, Any]], now: float | None = None) -> str:
    rows = ""
    for i, a in enumerate(AGENTS, start=1):
        s = states[a.id]
        if s["state"] == "running" and now and s.get("started"):
            el = f'{now - s["started"]:.0f} s'
        else:
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


def _paragraphs(text: str) -> str:
    """Agent narration (plain text with '-' bullets) to HTML."""
    out, items = [], []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line.startswith(("- ", "* ")):
            items.append(f"<li>{escape(line[2:].replace('**', ''))}</li>")
            continue
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
            items = []
        if line:
            out.append(f"<p>{escape(line.replace('**', ''))}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def results(report: dict[str, Any], confirmed: bool, button: str = "", gate_button: str = "") -> str:
    """Result panel. ``button`` is the confirm/undo control's HTML, placed under the appointments;
    ``gate_button`` is the clinician-confirmation control shown when urgent results hold up Next Steps."""
    st = report["stages"]
    if st.get("summarize", {}).get("status") not in ("ok", "demo"):
        reason = st.get("summarize", {}).get("reason") or st.get("summarize", {}).get("error") or ""
        return f'<p class="empty">Results appear when Summarize has run. {escape(reason)}</p>'
    s = summarize_view(st["summarize"]).model_dump()
    demo_note = '<p class="demo-note">Some agents are not built yet; their parts of this result use demo data from the synthetic case.</p>' if any(v.get("status") == "demo" for v in st.values()) else ""
    ledger = "".join(
        f'<li class="tr-{i["triage"]}"><span class="sym" aria-hidden="true"></span><div><b>{escape(i["title"])}</b>'
        f'<span class="tri">{TRIAGE_LABEL[i["triage"]]}{" · only in FINDINGS" if i.get("in_impression") is False else ""}</span>'
        f'<p>{escape(i["plain"])}</p><span class="owner">Owner: {escape(i["owner"])}</span>'
        + (f'<details><summary>Where your report says this</summary><blockquote>{escape(i["evidence"])}</blockquote></details>' if i.get("evidence") else "")
        + '</div></li>'
        for i in s["items"]
    )
    ns_stage = st.get("next_steps", {})
    ns = next_steps_view(ns_stage).model_dump() if ns_stage.get("status") in ("ok", "demo") else {}
    plan = ns_stage.get("plan") or {}
    ns_note = ""
    if ns_stage.get("status") == "awaiting_confirmation":
        ns_note = (f'<div class="gate"><b>A clinician needs to look at an urgent result first.</b>'
                   f'<p>{escape(ns_stage.get("markdown", "").replace("## Next steps", "").strip())}</p>{gate_button}</div>')
    elif ns_stage.get("status") == "skipped":
        ns_note = f'<p class="empty">No appointments planned: {escape(ns_stage.get("reason", ""))}.</p>'
    ns_text = ""
    if plan.get("summary"):
        ns_text = f'<details class="more"><summary>Read the full plan from the Next Steps agent</summary><div class="narration">{_paragraphs(plan["summary"])}</div></details>'
    if plan.get("caregiver_notes"):
        ns_text += "<h4>For whoever helps you</h4><ul>" + "".join(f"<li>{escape(n)}</li>" for n in plan["caregiver_notes"]) + "</ul>"
    appts = ""
    for k, a in enumerate(ns.get("appointments", []), start=1):
        day, time_ = _when(a["start"])
        flags = " · referral needed" * a["referral_required"] + " · prior auth" * a["prior_auth_required"]
        appts += (f'<tr class="{"punched" if confirmed else ""}"><td class="n">{k}</td><td><b>{escape(a["service_name"])}</b>'
                  f'<span>{escape(a["provider_name"])}{", " + escape(a["clinician"]) if a.get("clinician") else ""}{flags}</span></td>'
                  f'<td>{day}<span>{time_}</span></td><td class="num">{a["miles"]} mi</td><td class="num">${a["patient_pays"]:,.0f}</td>'
                  f'<td class="p">{CHECK if confirmed else ""}</td></tr>')
    total = f'${ns.get("total_patient_pays", 0):,.0f}'
    wplan = payload("wellness", st.get("wellness", {}))
    w_text = (st.get("wellness", {}).get("result") or {}).get("text", "")
    plan_ = wplan
    tips = ""
    if plan_.get("status") == "seek_care":
        tips = f'<li class="out"><b>Seek care</b> {escape(plan_.get("seek_care_message") or "")}</li>'
    for g in (plan_.get("nutrition") or {}).get("guidance", []):
        tips += f'<li><b>Nutrition</b> {escape(g["text"])}</li>'
    if plan_.get("activity"):
        tips += f'<li><b>Activity</b> {escape(plan_["activity"]["weekly_target"])}</li>'
    otc = plan_.get("otc") or {}
    for o in otc.get("options", []):
        tips += f'<li><b>OTC</b> {escape(o["ingredient"])}{" (" + escape(o["purpose"]) + ")" if o.get("purpose") else ""}</li>'
    for x in otc.get("excluded", []):
        tips += (f'<li class="out"><b>OTC</b> <span class="txt">{escape(x["name"])}</span>'
                 f'<em>Ruled out: {escape("; ".join(x["reasons"]))}</em></li>')
    status = "Confirmed. Nothing else is booked without you." if confirmed else "Proposed. Nothing is booked until you confirm."
    # Lead with what was found: drop the critic's audit sentences ("findings were checked ... no disputes")
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", s["headline"].strip()) if x]
    audit = ("extracted findings", "disput", "source text", "original report", "were verified")
    sentences = [x for x in sentences if not any(a in x.lower() for a in audit)] or sentences
    first, rest = sentences[0], " ".join(sentences[1:]) if len(" ".join(sentences)) > 140 else ""
    if not rest and len(sentences) > 1:
        first = " ".join(sentences)
    return f"""
    <section class="headline"><h2>{escape(first)}</h2>{f'<p class="lead">{escape(rest)}</p>' if rest else ""}{demo_note}</section>
    <div class="res-grid">
      <section><h3>What the reports found</h3><ul class="ledger">{ledger}</ul></section>
      <section><h3>Your course</h3>
        <table class="controls"><thead><tr><th>#</th><th>Appointment</th><th>When</th><th class="num">Dist.</th><th class="num">You pay</th><th></th></tr></thead>
        <tbody>{appts}</tbody></table>
        {ns_note}
        {"" if not ns.get("appointments") else f'<p class="total"><b>{total}</b> estimated · {status}</p>{button}'}
        {ns_text}
        <h3>While you wait</h3>
        <ul class="tips">{tips}</ul>
        {f'<details class="more"><summary>Read the full explanation from the Wellness agent</summary><div class="narration">{_paragraphs(w_text)}</div></details>' if w_text else ""}
      </section>
    </div>"""
