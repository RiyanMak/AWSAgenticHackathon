"""Demo payloads for agents that are not built yet, so the UI shows every handoff end to end.

Built from the bundled case's answer key (Lab, Radiology, Summarize) and the deterministic mock
network tools (Next Steps, Insurance). Every payload carries ``"demo": True`` and the UI labels it.
When a real agent returns ``status: ok`` for its stage, its output is used instead and the demo
for that stage never runs. Doubles as a reference implementation of the contracts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from functools import cache
from typing import Any

from .. import service
from .contracts import (
    InsuranceCheck,
    LedgerItem,
    NextStepsOutput,
    ProposedAppointment,
    SummarizeOutput,
    WellnessOutput,
    WellnessTip,
)

TODAY = "2026-10-23"  # data/README.md: use as "today" so slots are repeatable
SEVERITY = {"urgent": "urgent", "soon": "follow_up", "watch": "follow_up", "none": "info"}
# OTC options the Wellness demo considers, with what rules them out
OTC = [
    ("Cough syrup with dextromethorphan (DM)", ("dextromethorphan",), ()),
    ("Ibuprofen or naproxen for aches", ("ibuprofen", "naproxen", "nsaid", "aspirin"), ("anticoagulant", "ckd")),
    ("Acetaminophen for aches or fever, up to the label dose", ("acetaminophen",), ("liver",)),
]


@cache
def network():
    """data/network.py is a plain module beside the data; load it once."""
    path = service.find_data_dir() / "network.py"
    spec = importlib.util.spec_from_file_location("carerelay_data_network", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_case(case_id: str) -> dict[str, Any]:
    return json.loads((service.find_data_dir() / "cases" / f"{case_id}.json").read_text())


# ---------------------------------------------------------------------------- Lab, Radiology


def findings(case: dict, source: str) -> dict[str, Any]:
    rows = [a for a in case["answer_key"] if a["source"] == source]
    out = [
        {
            "id": f"{source[:3]}-{i + 1}",
            "source": source,
            "label": a["finding"],
            "value": f"{a['size_mm']} mm" if a.get("size_mm") else None,
            "severity": SEVERITY[a["triage"]],
            "in_impression": a.get("in_impression"),
            "answers_indication": not a["incidental"],
            "evidence": "answer key (demo)",
            "confidence": 1.0,
        }
        for i, a in enumerate(rows)
    ]
    return {"findings": out, "summary": f"{len(out)} {source} findings (demo)"}


# --------------------------------------------------------------------------------- Summarize


def _owner(services: list[str]) -> str:
    visits = [s for s in services if s.startswith("visit_")]
    if not visits or visits[0] == "visit_primary_care":
        return "Your PCP"
    return network().get_service(visits[0])["name"].split(" new patient")[0].replace(" visit", "")


def summarize(case: dict) -> SummarizeOutput:
    items = []
    for i, a in enumerate(case["answer_key"]):
        if not a["incidental"]:
            triage = "answered"
        else:
            triage = a["triage"]
        items.append(
            LedgerItem(
                id=f"L{i + 1}",
                title=a["finding"],
                plain=a["expected_followup"],
                source=a["source"],
                triage=triage,
                incidental=a["incidental"],
                in_impression=a.get("in_impression"),
                owner=_owner(a["followup_services"]),
                followup_services=a["followup_services"],
            )
        )
    answered = "; ".join(x.title for x in items if x.triage == "answered") or "Your reports were read"
    n = sum(x.triage in ("urgent", "soon") for x in items)
    tail = f" The reports also show {n} finding{'s' if n != 1 else ''} that need a follow-up." if n else " Nothing else needs a follow-up."
    return SummarizeOutput(headline=f"{answered}.{tail}", items=items)


# ---------------------------------------------------------------------------------- Wellness


def wellness(profile: dict[str, Any] | None) -> WellnessOutput:
    """Uses the real HistoryProfile when the History Agent ran: allergies and risk flags filter OTC."""
    profile = profile or {}
    allergies = " ".join(a.get("display", "") + " " + (a.get("detail") or "") for a in profile.get("allergies", [])).lower()
    flags = set(profile.get("risk_flags", []))
    tips = [
        WellnessTip(kind="nutrition", text="Plan meals around beans, oats, frozen vegetables and canned fish: cheap, filling, low in salt."),
        WellnessTip(kind="activity", text="Aim for 150 minutes a week of brisk walking, in 10-minute pieces if that is easier."),
        WellnessTip(kind="comfort", text="Warm fluids and honey can ease a cough while you wait."),
    ]
    for text, allergens, blocking_flags in OTC:
        hit = next((s for s in allergens if s in allergies), None)
        flag = next((f for f in blocking_flags if f in flags), None)
        reason = f"your record lists an allergy to {hit}" if hit else (f"risk flag: {flag}" if flag else None)
        tips.append(WellnessTip(kind="otc", text=text, excluded=bool(reason), reason=reason))
    return WellnessOutput(tips=tips)


# ------------------------------------------------------------------- Next Steps + Insurance


def next_steps(case: dict, summary: SummarizeOutput) -> NextStepsOutput:
    """Propose the nearest provider; Insurance checks it; re-propose until in network."""
    net = network()
    plan_id = case["Coverage"]["class"][0]["value"]
    zip_code = case["Patient"]["address"][0]["postalCode"]
    intake = case["intake"]
    member = net.get_member(case["Coverage"]["subscriberId"])
    ded, oop = member["deductible_met"], member["oop_met"]
    plan = net.get_plan(plan_id)
    out = NextStepsOutput()
    seen: set[str] = set()
    for item in summary.items:
        if item.triage not in ("urgent", "soon") or not item.followup_services:
            continue
        visits = [s for s in item.followup_services if s.startswith("visit_")]
        svc = (visits or item.followup_services)[0]
        if svc in seen:
            continue
        seen.add(svc)
        candidates = sorted(
            net.find_providers(svc, plan_id, zip_code, max_miles=intake.get("max_travel_miles")),
            key=lambda p: p["distance_miles"],
        )
        for rnd, cand in enumerate(candidates, start=1):
            ok = net.in_network(plan_id, cand["provider_id"])
            out.insurance_checks.append(
                InsuranceCheck(
                    round=rnd, ledger_id=item.id, service=svc, provider_id=cand["provider_id"],
                    provider_name=cand["name"], miles=cand["distance_miles"], in_network=ok,
                    verdict="accepted" if ok else "re-propose",
                    note=f"In network for {plan['name']}" if ok else f"Out of network for {plan['name']}; try the next closest",
                )
            )
            if not ok:
                continue
            slots = net.find_slots(cand["provider_id"], svc, TODAY, days=60, availability=intake.get("availability"))
            if not slots:
                continue
            est = net.estimate_cost(plan_id, svc, cand["provider_id"], deductible_met=ded, oop_met=oop)
            rule = plan["benefits"][net.get_service(svc)["category"]]
            if rule.get("after_deductible"):
                ded += min(est["allowed_amount"], max(0.0, plan["deductible"] - ded))
            oop += est["patient_pays"]
            out.appointments.append(
                ProposedAppointment(
                    ledger_ids=[item.id], service=svc, service_name=est["service_name"],
                    provider_id=cand["provider_id"], provider_name=cand["name"], clinician=cand["clinician"],
                    start=slots[0]["start"], miles=cand["distance_miles"], patient_pays=est["patient_pays"],
                    cost_note=" ".join(est["notes"]),
                    referral_required=net.requires_referral(plan_id, svc),
                    prior_auth_required=net.requires_prior_auth(plan_id, svc),
                )
            )
            break
    out.total_patient_pays = round(sum(a.patient_pays for a in out.appointments), 2)
    return out
