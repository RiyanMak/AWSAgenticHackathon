from datetime import date

import pytest

import network

PPO, HMO, MA, HDHP = "BLUEBONNET-PPO-500", "LONESTAR-HMO-2000", "PECAN-MA-HMO", "CEDAR-HDHP-3500"


def test_ppo_partial_deductible():
    est = network.estimate_cost(PPO, "ct_chest_wo", "IMG-BRIC", deductible_met=120, oop_met=310)
    # $380 remaining deductible, then 20% of the remaining $40.
    assert est["patient_pays"] == 388.0
    assert est["plan_pays"] == 32.0
    assert est["prior_auth_required"] and not est["referral_required"]


def test_hmo_out_of_network_not_covered():
    est = network.estimate_cost(HMO, "ct_chest_wo", "IMG-BRIC")
    assert not est["in_network"]
    assert est["patient_pays"] == round(420 * network.OON_BILLED_FACTOR, 2)
    assert est["plan_pays"] == 0.0


def test_ma_copay_with_hospital_price_factor():
    est = network.estimate_cost(MA, "ct_chest_wo", "IMG-SBMC")
    assert est["allowed_amount"] == 672.0
    assert est["patient_pays"] == 175


def test_hdhp_deductible_and_oop_cap():
    est = network.estimate_cost(HDHP, "mri_abdomen_renal", "IMG-BRIC", deductible_met=300)
    assert est["patient_pays"] == 1250.0
    capped = network.estimate_cost(PPO, "ct_chest_wo", "IMG-BRIC", deductible_met=500, oop_met=3990)
    assert capped["patient_pays"] == 10.0


def test_referral_rules():
    assert network.requires_referral(HMO, "visit_gynecology")
    assert network.requires_referral(MA, "visit_neurosurgery")
    assert not network.requires_referral(PPO, "visit_pulmonology")
    assert not network.requires_referral(HMO, "us_pelvis")


def test_find_providers_in_network_first():
    res = network.find_providers("visit_pulmonology", PPO, "78701")
    flags = [r["in_network"] for r in res]
    assert flags == sorted(flags, reverse=True)
    assert res[-1]["provider_id"] == "PULM-CAP"  # closest, but out of network for PPO


def test_find_slots_deterministic_and_filtered():
    avail = {"days": ["tue", "thu"], "times": "morning"}
    a = network.find_slots("IMG-BRIC", "ct_chest_wo", "2026-10-23", availability=avail)
    b = network.find_slots("IMG-BRIC", "ct_chest_wo", "2026-10-23", availability=avail)
    assert a == b and len(a) == 10
    for s in a:
        assert s["start"] >= "2026-10-26"  # lead_days = 3
        assert s["start"][11:13] < "12"
    assert {network.WEEKDAYS[date.fromisoformat(s["start"][:10]).weekday()] for s in a} <= {"tue", "thu"}


def test_find_slots_rejects_unoffered_service():
    with pytest.raises(ValueError):
        network.find_slots("LAB-HCCL-S", "ct_chest_wo", "2026-10-23")


def test_to_appointment_is_proposed():
    slot = network.find_slots("PCP-BFM", "visit_primary_care", "2026-10-23", limit=1)[0]
    appt = network.to_appointment(slot, "Linda Marquez", reason="Coronary calcification")
    assert appt["status"] == "proposed"
    assert appt["resourceType"] == "Appointment"
