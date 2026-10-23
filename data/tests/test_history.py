"""Medical history checks: well-formed, consistent with the case, and never spoiling the answer key."""

import re

import pytest

import build
import history
import network
import render

CASES = build.load_cases()
ids = lambda c: c["case_id"]  # noqa: E731

# A coded history condition that "explains" a finding (ARCHITECTURE.md expected-vs-incidental
# rule). If any of these appear for a finding the answer key marks incidental, the history
# would silently turn that finding into an expected one.
EXPLAINS = {
    "E11": ["a1c", "diabetes"],
    "N18": ["egfr", "ckd", "kidney function"],
    "E87.1": ["hyponatremia"],
    "E87.6": ["hypokalemia"],
    "E83.52": ["hypercalcemia"],
    "D5": ["anemia"],
    "D6": ["anemia"],
    "D75.1": ["hemoglobin"],
    "J43": ["emphysema", "copd", "hyperinflation"],
    "J44": ["emphysema", "copd", "hyperinflation"],
    "I71": ["aort"],
    "I25": ["coronary"],
    "E04": ["thyroid"],
    "E27": ["adrenal"],
    "D35.0": ["adrenal"],
    "K76.0": ["steatosis"],
    "N83.2": ["ovarian"],
    "D32": ["meningioma"],
    "N28.1": ["renal cyst"],
    "R91": ["nodule"],
    "E78": ["ldl"],
    "R03.0": ["blood pressure"],
    "I10": ["blood pressure"],
}


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_history_source_matches_pcp(case):
    h = case["history"]
    assert h["source"] in history.SOURCES
    has_pcp = bool(case["Patient"].get("generalPractitioner"))
    assert (h["source"] == "pcp_record") == has_pcp
    if has_pcp:
        clinic = network.get_provider(h["provider_id"])
        assert clinic["specialty"] == "Primary care"
        gp = case["Patient"]["generalPractitioner"][0]["display"]
        assert clinic["clinician"] in gp and clinic["name"] in gp
        assert h["printed"] <= case["portal"]["printed"]
    else:
        assert not h["care_team"]
    for m in h["care_team"]:
        if "provider_id" in m:
            assert network.get_provider(m["provider_id"])["clinician"] == m["name"]


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_history_codes_well_formed(case):
    h = case["history"]
    for c in h["conditions"]:
        assert re.fullmatch(r"[A-Z]\d{2}(\.[0-9A-Z]{1,4})?", c["icd10"]), c
    for m in h["medications"]:
        assert m["rxnorm"].isdigit(), m
    for a in h["allergies"]:
        assert a["category"] in {"medication", "food", "environment"}
        assert a["criticality"] in {"low", "high", "unable-to-assess"}
        assert (a["category"] == "medication") == ("rxnorm" in a), a
    assert not (h["allergies"] and h.get("no_known_allergies"))


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_questionnaire_items_have_patient_wording(case):
    h = case["history"]
    if h["source"] != "patient_questionnaire":
        return
    for key in ("conditions", "medications", "allergies", "procedures", "family_history"):
        for item in h[key]:
            assert item.get("as_written"), f"{key}: {item}"


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_no_allergy_conflicts_with_active_meds(case):
    h = case["history"]
    active = {m["rxnorm"] for m in h["medications"] if m["status"] == "active"}
    assert not active & {a.get("rxnorm") for a in h["allergies"]}


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_intake_meds_appear_in_history(case):
    """Intake meds should be in the history; ED-started meds may not be in a PCP record yet."""
    displays = " ".join(m["display"].lower() for m in case["history"]["medications"])
    for med in case["intake"]["medications"]:
        if "(from ED)" in med:
            continue
        assert re.split(r"[\s/-]", med)[0].lower() in displays, med


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_history_does_not_explain_incidental_findings(case):
    codes = [c["icd10"] for c in case["history"]["conditions"]]
    for item in case["answer_key"]:
        if not item["incidental"]:
            continue
        text = item["finding"].lower()
        for prefix, words in EXPLAINS.items():
            hit = [c for c in codes if c.startswith(prefix)]
            assert not (hit and any(w in text for w in words)), f"{hit} explains '{item['finding']}'"


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_history_fhir_and_pdf(case, tmp_path):
    res = history.to_fhir(case["history"])
    kinds = {r["resourceType"] for r in res}
    assert {"FamilyMemberHistory", "Observation", "AllergyIntolerance"} <= kinds
    h = case["history"]
    assert sum(r["resourceType"] == "Condition" for r in res) == len(h["conditions"])
    assert sum(r["resourceType"] == "MedicationStatement" for r in res) == len(h["medications"])
    out = render.render_history(case, tmp_path / "history.pdf")
    assert out.read_bytes().startswith(b"%PDF")
