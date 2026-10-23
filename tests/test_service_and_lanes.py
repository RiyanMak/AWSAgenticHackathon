"""service.handle and the three lane adapters, offline (no AWS calls)."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from carerelay import service

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_list_and_load_scenarios():
    scenarios = service.list_scenarios()
    assert len(scenarios) == 10 and scenarios[0]["case_id"] == "case_001"
    s = service.load_scenario("case_001")
    assert Path(s["history_pdf"]).exists() and "answer_key" not in s
    with pytest.raises(service.ServiceError):
        service.load_scenario("case_999")


def test_handle_scenario_offline():
    report = service.handle({"scenario": "case_005", "options": {"llm": False}})
    assert report["case_id"] == "case_005"
    assert report["stages"]["history"]["status"] == "ok"
    profile = report["stages"]["history"]["profile"]
    assert "anticoagulant" in profile["risk_flags"]
    lab, rad = report["stages"]["lab"], report["stages"]["radiology"]
    assert lab["status"] == "ok" and lab["result"]["extraction_method"] == "local_text"
    assert any(f["label"] == "Sodium" and f["value"] == "131 mmol/L" for f in lab["result"]["findings"])
    assert rad["status"] == "ok" and rad["result"]["exam"] == "CT HEAD WITHOUT CONTRAST"
    assert report["stages"]["summarize"]["status"] == "ok"
    assert report["stages"]["wellness"]["status"] == "ok"
    assert report["stages"]["next_steps"]["status"] == "ok"
    md = report["report"]["markdown"]
    assert "# CareRelay report" in md and "Apixaban" in md and service.DISCLAIMER in md


def test_handle_base64_upload_offline():
    pdf_b64 = base64.b64encode((ROOT / "data/output/case_004/history.pdf").read_bytes()).decode()
    report = service.handle({"inputs": {"history_pdf": pdf_b64, "intake": "Allergies: latex (rash)"}, "options": {"llm": False}})
    assert report["case_id"] is None
    assert report["stages"]["lab"]["status"] == "skipped" and report["stages"]["radiology"]["status"] == "skipped"
    prof = report["stages"]["history"]["profile"]
    assert prof["document_kind"] == "patient_questionnaire"
    assert any(a["display"] == "latex" for a in prof["allergies"])


def test_handle_base64_lab_and_radiology_offline():
    enc = lambda name: base64.b64encode((ROOT / f"data/output/case_007/{name}").read_bytes()).decode()  # noqa: E731
    report = service.handle({"inputs": {"labs_pdf": enc("labs.pdf"), "radiology_pdf": enc("radiology.pdf")},
                             "options": {"llm": False}})
    assert report["stages"]["history"]["status"] == "skipped"
    assert any(f["label"] == "ALT" for f in report["stages"]["lab"]["result"]["findings"])
    assert report["stages"]["radiology"]["result"]["extraction_method"] == "local_rules"
    md = report["report"]["markdown"]
    assert "## Lab results" in md and "## Radiology" in md


def test_bad_lab_pdf_does_not_crash_pipeline():
    report = service.handle({"inputs": {"labs_pdf": base64.b64encode(b"%PDF-1.4 garbage").decode()},
                             "options": {"llm": False}})
    assert report["stages"]["lab"]["status"] == "needs_clinical_reevaluation"


def test_handle_free_text_prompt():
    report = service.handle("please run case_002, parse only")
    assert report["case_id"] == "case_002"
    with pytest.raises(service.ServiceError):
        service.handle("hello")
    with pytest.raises(service.ServiceError):
        service.handle({})


def test_lambda_handler_offline(monkeypatch):
    monkeypatch.delenv("REPORT_BUCKET", raising=False)
    handler = _load(ROOT / "aws/lambda/handler.py", "carerelay_lambda_handler")
    assert handler._s3 is None

    listing = handler.handle({"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": None})
    assert listing["statusCode"] == 200 and len(json.loads(listing["body"])["scenarios"]) == 10

    resp = handler.handle({"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": {"scenario": "case_001", "llm": "0"}})
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["stages"]["history"]["status"] == "ok" and body["saved"] == {}

    post = handler.handle({
        "requestContext": {"http": {"method": "POST"}},
        "isBase64Encoded": True,
        "body": base64.b64encode(json.dumps({"scenario": "case_009", "options": {"llm": False}}).encode()).decode(),
    })
    assert json.loads(post["body"])["case_id"] == "case_009"

    bad = handler.handle({"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": {"scenario": "nope"}})
    assert bad["statusCode"] == 400


def test_agentcore_entrypoint_offline():
    pytest.importorskip("bedrock_agentcore")
    app_mod = _load(ROOT / "aws/agentcore/app.py", "carerelay_agentcore_app")
    out = app_mod.invoke({"prompt": "run case_003 with no llm"})
    assert out["case_id"] == "case_003"
    out = app_mod.invoke({"scenario": "case_001", "options": {"llm": False}})
    assert out["stages"]["history"]["status"] == "ok"
    err = app_mod.invoke({"prompt": "what can you do"})
    assert "error" in err and "case_001" in err["scenarios"]


def test_template_and_policy_are_consistent():
    policy = json.loads((ROOT / "aws/iam-bedrock-policy.json").read_text())
    actions = {a for s in policy["Statement"] for a in s["Action"]}
    template = (ROOT / "aws/template.yaml").read_text()
    for a in ("bedrock:InvokeModel", "bedrock-mantle:CreateInference", "comprehendmedical:InferICD10CM"):
        assert a in actions and a in template
    assert "ExpirationInDays" in template and "FunctionUrlConfig" in template
    assert "bedrock-agentcore.amazonaws.com" in template


def test_full_flow_offline_case_001():
    report = service.handle({"scenario": "case_001", "options": {"llm": False}})
    st = report["stages"]
    assert [st[n]["status"] for n in service.STAGES] == ["ok"] * 6
    record = st["summarize"]["case_record"]
    assert record["ledger"] and record["visit_reason"].startswith("Persistent cough")
    plan = st["next_steps"]["plan"]
    proposed = [s for s in plan["steps"] if s["status"] == "proposed"]
    assert proposed and all(s["in_network"] for s in proposed)
    assert all(s["appointment"]["status"] == "proposed" for s in proposed)
    md = report["report"]["markdown"]
    for heading in ("## Summary", "## Wellness while you wait", "## Next steps", "### Incidental ledger"):
        assert heading in md


def test_urgent_case_waits_for_confirmation():
    report = service.handle({"scenario": "case_007", "options": {"llm": False}})
    ns = report["stages"]["next_steps"]
    assert ns["status"] == "awaiting_confirmation" and ns["needs_confirmation"]
    confirmed = service.handle({"scenario": "case_007", "options": {"llm": False, "human_confirmed": True}})
    steps = confirmed["stages"]["next_steps"]["plan"]["steps"]
    assert any(s["triage"] == "urgent" and s["status"] == "proposed" for s in steps)


def test_upload_without_coverage_skips_next_steps():
    pdf = base64.b64encode((ROOT / "data/output/case_001/labs.pdf").read_bytes()).decode()
    report = service.handle({"inputs": {"labs_pdf": pdf}, "options": {"llm": False}})
    st = report["stages"]
    assert st["summarize"]["status"] == "ok" and any("history" in g for g in st["summarize"]["case_record"]["gaps"])
    assert st["next_steps"]["status"] == "skipped"


@pytest.mark.parametrize("case_id", [f"case_{i:03d}" for i in range(1, 11)])
def test_every_case_runs_end_to_end_offline(case_id):
    report = service.handle({"scenario": case_id, "options": {"llm": False, "human_confirmed": True}})
    for name in service.STAGES:
        assert report["stages"][name]["status"] in ("ok", "skipped"), (name, report["stages"][name])
