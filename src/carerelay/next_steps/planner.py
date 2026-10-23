"""Deterministic Next Steps planner: findings -> services -> in-network providers -> slots -> costs.

Every proposal it makes is checkable: the provider offers the service, is in the plan's network (or is flagged
as out of network when the plan covers that), the slot fits the patient's days/times and the triage window, and
the cost comes from the payer tools priced in date order. Appointments are FHIR "proposed"; a human confirms.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from carerelay.insurance import core as insurance
from carerelay.insurance.schema import CostCheck, CoverageProfile
from carerelay.network import net

from .catalog import DUE_DAYS, TRIAGE_ORDER, services_for, valid_services
from .schema import NextStepsPlan, NextStepsRequest, NoAction, ServiceStep

RADIUS_ROUNDS = (1.0, 1.5, 2.25)   # widen the travel radius up to 3 rounds (docs/ARCHITECTURE.md step 4)
MAX_CANDIDATES = 6
ORDER_NEEDED = {"imaging_basic", "imaging_advanced", "lab", "diagnostic_test", "procedure"}
TRAVEL_BUFFER = timedelta(minutes=30)
SLOTS_PER_PROVIDER = 30


def _free(slot: dict, busy: list[tuple[datetime, datetime]]) -> bool:
    """No overlap with already proposed appointments, keeping a travel buffer between them."""
    start, end = datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])
    return all(end + TRAVEL_BUFFER <= b0 or start >= b1 + TRAVEL_BUFFER for b0, b1 in busy)


def _gather(request: NextStepsRequest, choices: dict[str, list[str]], plan: NextStepsPlan) -> dict[str, dict]:
    """Findings -> {service: {finding_ids, reasons, triage}}, most urgent triage wins when findings share a service."""
    wanted: dict[str, dict[str, Any]] = {}
    for f in request.findings:
        if f.triage == "none":
            plan.no_action.append(NoAction(finding_id=f.id, label=f.label, reason="Triage: no follow-up needed."))
            continue
        services = choices.get(f.id, f.services if f.services is not None else services_for(f))
        if services is None and f.source == "lab":
            services = ["visit_primary_care"]   # routine abnormal labs are the PCP's to review
        if services is None:
            plan.unmapped_findings.append(f.id)
            services = ["visit_primary_care"]
            plan.notes.append(f"No follow-up rule for '{f.label}'; proposing a primary care visit to decide next steps.")
        if not services:
            plan.no_action.append(NoAction(finding_id=f.id, label=f.label, reason="Known finding; nothing to book."))
            continue
        known, unknown = valid_services(services)
        for s in unknown:
            plan.notes.append(f"Ignored unknown service '{s}' for '{f.label}'.")
        for s in known:
            w = wanted.setdefault(s, {"finding_ids": [], "reasons": [], "triage": f.triage})
            w["finding_ids"].append(f.id)
            w["reasons"].append(f.label)
            if TRIAGE_ORDER.index(f.triage) < TRIAGE_ORDER.index(w["triage"]):
                w["triage"] = f.triage
    return wanted


def _add_referral_visit(wanted: dict[str, dict], coverage: CoverageProfile) -> list[str]:
    """HMO-style plans: a specialist visit needs a PCP referral, so make sure a PCP visit comes first."""
    needing = [s for s, w in wanted.items()
               if w["triage"] in DUE_DAYS and net().requires_referral(coverage.plan_id, s)]
    if not needing:
        return []
    triage = min((wanted[s]["triage"] for s in needing), key=TRIAGE_ORDER.index)
    pcp = wanted.setdefault("visit_primary_care", {"finding_ids": [], "reasons": [], "triage": triage})
    if TRIAGE_ORDER.index(triage) < TRIAGE_ORDER.index(pcp["triage"]):
        pcp["triage"] = triage
    pcp["reasons"].append("Referral for " + ", ".join(net().get_service(s)["name"] for s in needing))
    return needing


def _candidates(service: str, request: NextStepsRequest, coverage: CoverageProfile,
                step: ServiceStep) -> list[dict]:
    established = set(request.patient.established_provider_ids)

    def usable(rows):
        rows = [r for r in rows if r["accepting_new_patients"] or r["provider_id"] in established]
        return sorted(rows, key=lambda r: (r["provider_id"] not in established, r["distance_miles"]))

    radius = request.patient.max_travel_miles
    for round_no, factor in enumerate(RADIUS_ROUNDS, start=1):
        radius = request.patient.max_travel_miles * factor
        step.search_rounds = round_no
        rows = usable(net().find_providers(service, coverage.plan_id, request.patient.zip, max_miles=radius,
                                           in_network_only=True))
        if rows:
            if round_no > 1:
                step.notes.append(f"No in-network option within {request.patient.max_travel_miles:g} miles; "
                                  f"widened the search to {radius:g} miles.")
            return rows
    if coverage.out_of_network_covered:
        rows = usable(net().find_providers(service, coverage.plan_id, request.patient.zip, max_miles=radius))
        if rows:
            step.notes.append(f"No in-network option within {radius:g} miles; showing an out-of-network option, "
                              "which costs more.")
        return rows
    return []


def _schedule(service: str, w: dict, request: NextStepsRequest, coverage: CoverageProfile,
              earliest: date, busy: list[tuple[datetime, datetime]]) -> ServiceStep:
    svc = net().get_service(service)
    step = ServiceStep(service=service, service_name=svc["name"], finding_ids=w["finding_ids"], reasons=w["reasons"],
                       triage=w["triage"], status="proposed")
    if w["triage"] not in DUE_DAYS:
        step.status = "discuss_with_pcp"
        step.notes.append("Not time-sensitive: bring this up at your next primary care visit.")
        return step

    today = date.fromisoformat(request.today)
    due = today + timedelta(days=DUE_DAYS[w["triage"]])
    step.due_by = due.isoformat()
    candidates = _candidates(service, request, coverage, step)
    if not candidates:
        step.status = "no_option_found"
        step.notes.append("No provider offering this service was found in network; ask the plan or your PCP.")
        return step

    established = set(request.patient.established_provider_ids)
    lang = request.patient.preferred_language
    options: list[tuple[dict, dict, CostCheck]] = []
    for window_end in (due, due + timedelta(days=DUE_DAYS[w["triage"]])):
        for c in candidates[:MAX_CANDIDATES]:
            slots = net().find_slots(c["provider_id"], service, start=earliest, days=(window_end - earliest).days,
                                     availability=request.patient.availability, limit=SLOTS_PER_PROVIDER)
            slot = next((sl for sl in slots if _free(sl, busy)), None)
            if slot:
                options.append((c, slot, insurance.estimate(coverage, service, c["provider_id"])))
        if options:
            if window_end != due:
                step.notes.append(f"No opening that fits your schedule before {due.isoformat()}; showing the earliest after.")
            break
    if not options:
        step.status = "no_option_found"
        step.notes.append("No opening fits your available days and times; call the office to ask about other times.")
        return step

    c, slot, cost = min(options, key=lambda o: (
        o[0]["provider_id"] not in established, lang not in o[0]["languages"], o[2].patient_pays,
        o[1]["start"], o[0]["distance_miles"]))
    step.provider_id, step.provider_name, step.clinician = c["provider_id"], c["name"], c["clinician"]
    step.distance_miles, step.in_network = c["distance_miles"], c["in_network"]
    step.established = c["provider_id"] in established
    step.language_match = lang in c["languages"]
    step.slot_start, step.slot_end = slot["start"], slot["end"]
    busy.append((datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])))
    step.appointment = net().to_appointment(slot, request.patient.display, reason="; ".join(w["reasons"]))
    step.prior_auth_required, step.referral_required = cost.prior_auth_required, cost.referral_required
    if step.established:
        step.notes.append("A provider you already see.")
    if not step.language_match:
        step.notes.append(f"No nearby option lists language '{lang}'; ask about an interpreter.")
    if svc["category"] in ORDER_NEEDED:
        step.notes.append("Needs an order from a clinician (your PCP or the specialist).")
    if cost.prior_auth_required:
        step.notes.append("Needs prior authorization; the ordering office requests it before the appointment.")
    if cost.referral_required:
        step.notes.append("Needs a referral from your primary care doctor (planned first).")
    return step


def plan_followups(request: NextStepsRequest, coverage: CoverageProfile,
                   service_choices: dict[str, list[str]] | None = None) -> NextStepsPlan:
    plan = NextStepsPlan(coverage=coverage)
    wanted = _gather(request, service_choices or {}, plan)
    needing_referral = _add_referral_visit(wanted, coverage)

    today = date.fromisoformat(request.today)
    # Order of care: the PCP visit first (it writes referrals and orders), then tests that need an order, then
    # specialist visits, which should follow the tests for the same finding so the results are there to review.
    def phase(service: str) -> int:
        if service == "visit_primary_care":
            return 0
        return 1 if net().get_service(service)["category"] in ORDER_NEEDED else 2

    order = sorted(wanted, key=lambda s: (phase(s), TRIAGE_ORDER.index(wanted[s]["triage"])))
    scheduled: list[ServiceStep] = []
    busy: list[tuple[datetime, datetime]] = []
    for service in order:
        w = wanted[service]
        after = []   # appointments this one should follow
        if phase(service) > 0:
            after += [s for s in scheduled if s.service == "visit_primary_care"
                      and (service in needing_referral or phase(service) == 1)]
        if phase(service) == 2:
            after += [s for s in scheduled if phase(s.service) == 1 and set(s.finding_ids) & set(w["finding_ids"])]
        earliest = today
        days = [date.fromisoformat(s.slot_start[:10]) for s in after if s.slot_start]
        if days:
            candidate = max(days) + timedelta(days=1)
            # an urgent step must not slip past its window just to follow another appointment
            if w["triage"] != "urgent" or candidate <= today + timedelta(days=DUE_DAYS["urgent"] - 3):
                earliest = candidate
        step = _schedule(service, w, request, coverage, earliest, busy)
        scheduled.append(step)

    triage_rank = {s: i for i, s in enumerate(TRIAGE_ORDER)}
    plan.steps = sorted(scheduled, key=lambda s: (s.status != "proposed", s.slot_start or "", triage_rank[s.triage]))

    # Price proposals in date order, carrying the deductible / out-of-pocket spend forward.
    deductible_met, oop_met = coverage.deductible_met, coverage.oop_met
    for step in sorted((s for s in plan.steps if s.status == "proposed"), key=lambda s: s.slot_start):
        cost = insurance.estimate(coverage, step.service, step.provider_id, deductible_met, oop_met)
        step.patient_pays, step.allowed_amount = cost.patient_pays, cost.allowed_amount
        oop_met += cost.patient_pays
        if insurance.counts_toward_deductible(coverage, step.service):
            deductible_met = min(coverage.deductible, deductible_met + cost.patient_pays)
    plan.total_patient_pays = round(sum(s.patient_pays or 0 for s in plan.steps), 2)
    plan.summary = template_summary(plan)
    return plan


def template_summary(plan: NextStepsPlan) -> str:
    proposed = [s for s in plan.steps if s.status == "proposed"]
    if not proposed and not plan.steps:
        return "No follow-up appointments are needed based on these results."
    parts = []
    if proposed:
        urgent = sum(s.triage == "urgent" for s in proposed)
        parts.append(f"{len(proposed)} follow-up appointment(s) proposed"
                     + (f", {urgent} of them urgent (within 2 weeks)" if urgent else "")
                     + f", estimated total ${plan.total_patient_pays:,.2f} out of pocket.")
        first = min(proposed, key=lambda s: s.slot_start)
        parts.append(f"First: {first.service_name} at {first.provider_name} on {first.slot_start.replace('T', ' at ')}.")
    discuss = [s.service_name for s in plan.steps if s.status == "discuss_with_pcp"]
    if discuss:
        parts.append("To discuss at your next primary care visit: " + ", ".join(discuss) + ".")
    missing = [s.service_name for s in plan.steps if s.status == "no_option_found"]
    if missing:
        parts.append("Could not find an option for: " + ", ".join(missing) + ".")
    parts.append("Nothing is booked until you confirm.")
    return " ".join(parts)
