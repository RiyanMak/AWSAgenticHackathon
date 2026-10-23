"""Typed outputs of the Insurance Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CoverageProfile(BaseModel):
    plan_id: str
    plan_name: str
    payer: str
    plan_type: str
    network_id: str
    member_id: str | None = None
    deductible: float
    deductible_met: float = 0.0
    oop_max: float
    oop_met: float = 0.0
    accumulators_as_of: str | None = None
    referral_required_for: list[str] = Field(default_factory=list, description="Service categories, e.g. office_specialist")
    prior_auth_categories: list[str] = Field(default_factory=list)
    prior_auth_services: list[str] = Field(default_factory=list)
    out_of_network_covered: bool = False
    summary: str = ""
    notes: list[str] = Field(default_factory=list)

    @property
    def deductible_remaining(self) -> float:
        return max(0.0, self.deductible - self.deductible_met)

    @property
    def oop_remaining(self) -> float:
        return max(0.0, self.oop_max - self.oop_met)


class CostCheck(BaseModel):
    service: str
    service_name: str
    provider_id: str | None
    in_network: bool
    allowed_amount: float
    patient_pays: float
    plan_pays: float
    possible_balance_bill: float = 0.0
    prior_auth_required: bool
    referral_required: bool
    notes: list[str] = Field(default_factory=list)


class CoverageBrief(BaseModel):
    """What the Insurance Agent's model writes. Numbers come from tools, never from the model."""

    summary: str = Field(description="2-4 plain sentences: plan type, what is left on the deductible and out-of-pocket "
                                     "max, and whether referrals or prior authorization apply. No new numbers.")
    cost_tips: list[str] = Field(default_factory=list, description="Up to 3 short, factual tips that follow from the "
                                                                   "plan rules (e.g. stay in network, get the referral first).")
