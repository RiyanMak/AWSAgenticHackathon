import json

from carerelay.history import build_history_profile, run_history_agent
from carerelay.history.tools import HISTORY_TOOLS, check_finding_explained, derive_risk_flags, parse_fhir_history


def test_build_merges_mimic_and_intake(mimic_dir, mimic_subject):
    intake = "Allergies: penicillin (hives)\nDoctors: nephrologist Dr. Patel"
    profile = build_history_profile(mimic_dir=mimic_dir, mimic_subject_id=mimic_subject, intake_text=intake, offline=True)
    assert profile.source == "csv"
    assert profile.conditions  # from MIMIC
    assert profile.allergies and profile.allergies[0].display == "penicillin"  # from intake
    assert "nephrology" in profile.known_specialists
    assert not any("no allergy table" in w for w in profile.warnings), "intake allergies resolve the MIMIC warning"


def test_run_without_llm_sets_no_summary(synthea_bundle_path):
    profile = run_history_agent(fhir_bundle=synthea_bundle_path, use_llm=False)
    assert profile.summary == ""
    assert profile.conditions


def test_run_degraded_input_skips_llm(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("[]")
    profile = run_history_agent(fhir_bundle=bad, use_llm=True)  # must not call Bedrock
    assert profile.source == "degraded"
    assert "treated as incidental" in profile.summary


def test_tools_are_callable_as_plain_functions(synthea_bundle_path):
    assert len(HISTORY_TOOLS) == 6
    data = parse_fhir_history(bundle_path=str(synthea_bundle_path))
    assert data["source"] == "fhir"
    flags = derive_risk_flags(profile_json=json.dumps(data))
    assert flags["risk_flags"] == data["risk_flags"]
    verdict = check_finding_explained(finding_label="Glucose", profile_json=json.dumps(data))
    assert verdict["incidental"] == (not verdict["explained_by"])
    assert parse_fhir_history(bundle_path="/nope.json")["error"]


def test_tool_specs_have_descriptions():
    for t in HISTORY_TOOLS:
        spec = t.tool_spec
        assert spec["name"] and spec["description"]
        assert "json" in spec["inputSchema"]
