"""Mock insurance plans and provider network, with deterministic lookup tools.

Everything here is plain Python over the JSON in network/, so agents can call these
as tools and get the same numbers every time. The LLM decides and explains; this
module does the math.

    import network
    network.find_providers("ct_chest_wo", "BLUEBONNET-PPO-500", "78745")
    network.find_slots("IMG-BRIC", "ct_chest_wo", start="2026-10-23",
                       availability={"days": ["tue", "thu"], "times": "morning"})
    network.estimate_cost("BLUEBONNET-PPO-500", "ct_chest_wo", "IMG-BRIC",
                          deductible_met=120, oop_met=310)
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "network"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
OON_BILLED_FACTOR = 1.8


@cache
def _load(name: str):
    return json.loads((DATA / f"{name}.json").read_text())


def plans() -> dict[str, dict]:
    return {p["plan_id"]: p for p in _load("plans")}


def services() -> dict[str, dict]:
    return {k: v for k, v in _load("services").items() if not k.startswith("_")}


def providers() -> dict[str, dict]:
    return {p["provider_id"]: p for p in _load("providers")}


def get_plan(plan_id: str) -> dict:
    try:
        return plans()[plan_id]
    except KeyError:
        raise KeyError(f"Unknown plan_id {plan_id!r}; known: {sorted(plans())}") from None


def get_service(service_key: str) -> dict:
    try:
        return services()[service_key]
    except KeyError:
        raise KeyError(f"Unknown service {service_key!r}") from None


def get_provider(provider_id: str) -> dict:
    try:
        return providers()[provider_id]
    except KeyError:
        raise KeyError(f"Unknown provider_id {provider_id!r}") from None


def get_member(subscriber_id: str) -> dict:
    """Year-to-date accumulators for a member (mock payer eligibility lookup)."""
    return _load("member_accumulators")[subscriber_id]


def distance_miles(zip_a: str, zip_b: str) -> float:
    zc = _load("zip_centroids")
    (lat1, lon1), (lat2, lon2) = zc[zip_a], zc[zip_b]
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    miles = 3958.8 * 2 * math.asin(math.sqrt(a))
    return round(max(miles, 1.0), 1)


def in_network(plan_id: str, provider_id: str) -> bool:
    return get_plan(plan_id)["network_id"] in get_provider(provider_id)["networks"]


def requires_prior_auth(plan_id: str, service_key: str) -> bool:
    pa = get_plan(plan_id)["prior_auth"]
    return service_key in pa["services"] or get_service(service_key)["category"] in pa["categories"]


def requires_referral(plan_id: str, service_key: str) -> bool:
    return get_service(service_key)["category"] in get_plan(plan_id)["referral_required_for"]


def find_providers(
    service_key: str,
    plan_id: str,
    patient_zip: str,
    max_miles: float | None = None,
    in_network_only: bool = False,
) -> list[dict]:
    """Providers offering a service, in-network first, then by distance."""
    get_service(service_key)
    out = []
    for prov in providers().values():
        if service_key not in prov["services"]:
            continue
        dist = distance_miles(patient_zip, prov["zip"])
        inn = in_network(plan_id, prov["provider_id"])
        if (max_miles is not None and dist > max_miles) or (in_network_only and not inn):
            continue
        out.append(
            {
                "provider_id": prov["provider_id"],
                "name": prov["name"],
                "clinician": prov["clinician"],
                "specialty": prov["specialty"],
                "address": prov["address"],
                "phone": prov["phone"],
                "distance_miles": dist,
                "in_network": inn,
                "accepting_new_patients": prov["accepting_new_patients"],
                "languages": prov["languages"],
                "lead_days": prov["lead_days"],
            }
        )
    return sorted(out, key=lambda r: (not r["in_network"], r["distance_miles"]))


def _is_booked(provider_id: str, start: datetime, booked_pct: int) -> bool:
    h = hashlib.sha256(f"{provider_id}|{start.isoformat()}".encode()).hexdigest()
    return int(h[:8], 16) % 100 < booked_pct


def find_slots(
    provider_id: str,
    service_key: str,
    start: date | str,
    days: int = 28,
    availability: dict | None = None,
    limit: int = 10,
) -> list[dict]:
    """Open slots at a provider, deterministic for a given start date.

    availability: {"days": ["mon", ...], "times": "morning" | "afternoon" | "any"},
    the same shape as a case file's intake.availability.
    """
    prov = get_provider(provider_id)
    svc = get_service(service_key)
    if service_key not in prov["services"]:
        raise ValueError(f"{provider_id} does not offer {service_key}")
    start = date.fromisoformat(start) if isinstance(start, str) else start
    avail = availability or {}
    ok_days = set(avail.get("days") or WEEKDAYS)
    times = avail.get("times", "any")
    step = timedelta(minutes=svc["minutes"])

    slots = []
    for offset in range(prov["lead_days"], days + 1):
        day = start + timedelta(days=offset)
        dow = WEEKDAYS[day.weekday()]
        if dow not in prov["hours"]["days"] or dow not in ok_days:
            continue
        for block in prov["hours"]["blocks"]:
            b0, b1 = (datetime.combine(day, datetime.strptime(t, "%H:%M").time()) for t in block.split("-"))
            t = b0
            while t + step <= b1:
                if times == "morning" and t.hour >= 12:
                    break
                if not (times == "afternoon" and t.hour < 12) and not _is_booked(provider_id, t, prov["booked_pct"]):
                    slots.append(
                        {
                            "provider_id": provider_id,
                            "service": service_key,
                            "start": t.isoformat(timespec="minutes"),
                            "end": (t + step).isoformat(timespec="minutes"),
                        }
                    )
                    if len(slots) >= limit:
                        return slots
                t += step
    return slots


def to_appointment(slot: dict, patient_display: str, reason: str | None = None) -> dict:
    """FHIR-shaped Appointment, status 'proposed'. Nothing is booked."""
    prov = get_provider(slot["provider_id"])
    actor = prov["clinician"] or prov["name"]
    return {
        "resourceType": "Appointment",
        "status": "proposed",
        "serviceType": [{"text": get_service(slot["service"])["name"]}],
        "reasonCode": [{"text": reason}] if reason else [],
        "start": slot["start"],
        "end": slot["end"],
        "participant": [
            {"actor": {"display": patient_display}, "status": "needs-action"},
            {"actor": {"display": f"{actor}, {prov['name']}"}, "status": "needs-action"},
        ],
        "_provider_id": prov["provider_id"],
    }


def estimate_cost(
    plan_id: str,
    service_key: str,
    provider_id: str | None = None,
    deductible_met: float = 0.0,
    oop_met: float = 0.0,
) -> dict:
    """Patient cost estimate for one service. Simplified; illustrative only."""
    plan = get_plan(plan_id)
    svc = get_service(service_key)
    factor = get_provider(provider_id)["price_factor"] if provider_id else 1.0
    allowed = round(svc["allowed"] * factor, 2)
    inn = in_network(plan_id, provider_id) if provider_id else True
    notes = []
    balance_bill = 0.0

    if not inn:
        oon = plan["out_of_network"]
        billed = round(allowed * OON_BILLED_FACTOR, 2)
        if not oon["covered"]:
            patient = billed
            notes.append(f"Out of network: {plan['name']} does not cover out-of-network care; patient pays full billed charge.")
        else:
            ded_part = min(allowed, oon["deductible"])
            patient = ded_part + (allowed - ded_part) * oon["coinsurance"]
            balance_bill = round(billed - allowed, 2)
            notes.append(
                f"Out of network: separate ${oon['deductible']:,} deductible (assumed unmet), then "
                f"{oon['coinsurance']:.0%} coinsurance; provider may balance-bill up to ${balance_bill:,.2f}."
            )
    else:
        rule = plan["benefits"][svc["category"]]
        if "copay" in rule:
            patient = min(rule["copay"], allowed)
            notes.append(f"{svc['category']}: ${rule['copay']} copay.")
        else:
            remaining = max(0.0, plan["deductible"] - deductible_met) if rule.get("after_deductible") else 0.0
            ded_part = min(allowed, remaining)
            patient = ded_part + (allowed - ded_part) * rule["coinsurance"]
            notes.append(
                f"{svc['category']}: ${ded_part:,.2f} toward deductible "
                f"(${remaining:,.2f} remaining of ${plan['deductible']:,}), then {rule['coinsurance']:.0%} coinsurance."
            )
        cap = max(0.0, plan["oop_max"] - oop_met)
        if patient > cap:
            notes.append(f"Capped by out-of-pocket max (${cap:,.2f} remaining).")
            patient = cap

    patient = round(patient, 2)
    return {
        "plan_id": plan_id,
        "service": service_key,
        "service_name": svc["name"],
        "provider_id": provider_id,
        "in_network": inn,
        "allowed_amount": allowed,
        "patient_pays": patient,
        "plan_pays": round(max(allowed - patient, 0.0), 2) if inn or plan["out_of_network"]["covered"] else 0.0,
        "possible_balance_bill": balance_bill,
        "prior_auth_required": requires_prior_auth(plan_id, service_key),
        "referral_required": requires_referral(plan_id, service_key),
        "notes": notes,
    }
