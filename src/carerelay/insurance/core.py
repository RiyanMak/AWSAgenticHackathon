"""Deterministic insurance logic over the mock payer (data/network.py). No model calls here."""

from __future__ import annotations

from typing import Any

from carerelay.network import net

from .schema import CostCheck, CoverageProfile


def coverage_profile(coverage: dict[str, Any]) -> CoverageProfile:
    """FHIR-shaped Coverage (plan in class[0].value, member in subscriberId) -> plan rules + accumulators."""
    try:
        plan_id = coverage["class"][0]["value"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Coverage has no plan in class[0].value") from None
    plan = net().get_plan(plan_id)
    member_id = coverage.get("subscriberId")
    notes = []
    try:
        member = net().get_member(member_id) if member_id else None
    except KeyError:
        member = None
    if member is None:
        notes.append("Member not found in the payer lookup; assuming nothing spent toward the deductible yet.")
    elif member["plan_id"] != plan_id:
        notes.append(f"Payer lookup lists plan {member['plan_id']} for this member, not {plan_id}; using the card's plan.")
    oon = plan["out_of_network"]
    return CoverageProfile(
        plan_id=plan_id, plan_name=plan["name"], payer=plan["payer"], plan_type=plan["type"],
        network_id=plan["network_id"], member_id=member_id,
        deductible=plan["deductible"], deductible_met=(member or {}).get("deductible_met", 0.0),
        oop_max=plan["oop_max"], oop_met=(member or {}).get("oop_met", 0.0),
        accumulators_as_of=(member or {}).get("as_of"),
        referral_required_for=plan["referral_required_for"],
        prior_auth_categories=plan["prior_auth"]["categories"], prior_auth_services=plan["prior_auth"]["services"],
        out_of_network_covered=oon["covered"], notes=notes,
    )


def in_network(profile: CoverageProfile, provider_id: str) -> bool:
    return net().in_network(profile.plan_id, provider_id)


def estimate(profile: CoverageProfile, service: str, provider_id: str | None,
             deductible_met: float | None = None, oop_met: float | None = None) -> CostCheck:
    """Price one service; pass running accumulators to price a sequence of visits."""
    est = net().estimate_cost(
        profile.plan_id, service, provider_id,
        deductible_met=profile.deductible_met if deductible_met is None else deductible_met,
        oop_met=profile.oop_met if oop_met is None else oop_met,
    )
    return CostCheck(
        service=service, service_name=est["service_name"], provider_id=provider_id, in_network=est["in_network"],
        allowed_amount=est["allowed_amount"], patient_pays=est["patient_pays"], plan_pays=est["plan_pays"],
        possible_balance_bill=est["possible_balance_bill"], prior_auth_required=est["prior_auth_required"],
        referral_required=est["referral_required"], notes=est["notes"],
    )


def counts_toward_deductible(profile: CoverageProfile, service: str) -> bool:
    category = net().get_service(service)["category"]
    return bool(net().get_plan(profile.plan_id)["benefits"].get(category, {}).get("after_deductible"))


def template_summary(profile: CoverageProfile) -> str:
    text = (f"{profile.plan_name} ({profile.plan_type}). "
            f"${profile.deductible_remaining:,.0f} of the ${profile.deductible:,.0f} deductible and "
            f"${profile.oop_remaining:,.0f} of the ${profile.oop_max:,.0f} out-of-pocket maximum remain this year.")
    if profile.referral_required_for:
        text += " Specialist visits need a referral from your primary care doctor."
    if profile.prior_auth_categories or profile.prior_auth_services:
        text += " Some imaging or procedures need prior authorization, which the ordering office requests."
    text += (" Out-of-network care is partly covered at a higher cost." if profile.out_of_network_covered
             else " Out-of-network care is not covered.")
    return text
