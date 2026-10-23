"""Drag-and-drop portal flow: unlabelled PDFs are sorted by content and stages stream in order."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from carerelay import service

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / "data" / "output").glob("case_*"))


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
def test_classify_every_bundled_pdf(case_dir):
    assert service.classify_pdf((case_dir / "history.pdf").read_bytes()) == "history"
    assert service.classify_pdf((case_dir / "labs.pdf").read_bytes()) == "labs"
    assert service.classify_pdf((case_dir / "radiology.pdf").read_bytes()) == "radiology"


def test_classify_garbage_is_unknown():
    assert service.classify_pdf(b"not a pdf") == "unknown"


def test_sort_documents_dedupes_and_warns():
    d = ROOT / "data/output/case_002"
    docs = [(d / "labs.pdf").read_bytes(), (d / "history.pdf").read_bytes(), (d / "labs.pdf").read_bytes(), b"junk"]
    sorted_docs, warnings = service.sort_documents(docs)
    assert set(sorted_docs) == {"labs", "history"}
    assert len(warnings) == 2 and "second labs" in warnings[0] and "not recognised" in warnings[1]


def test_drop_three_pdfs_runs_pipeline_offline():
    d = ROOT / "data/output/case_001"
    docs = [base64.b64encode((d / n).read_bytes()).decode() for n in ("radiology.pdf", "history.pdf", "labs.pdf")]
    events = list(service.iter_stages({"inputs": {"documents": docs}, "options": {"llm": False}}))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "inputs" and kinds[-1] == "report"
    assert events[0]["present"] == {"history": True, "lab": True, "radiology": True}
    stage_names = [e["name"] for e in events if e["event"] == "stage"]
    assert set(stage_names) == set(service.STAGES) and len(stage_names) == len(service.STAGES)
    report = events[-1]["report"]
    assert report["case_id"] is None
    assert report["stages"]["history"]["status"] == "ok"
    assert report["stages"]["lab"]["status"] == "ok" and report["stages"]["lab"]["result"]["rows"]
    assert report["stages"]["radiology"]["status"] == "ok"
    assert "input_warnings" not in report


def test_drop_only_a_lab_pdf():
    d = ROOT / "data/output/case_004"
    report = service.handle({"inputs": {"documents": [(d / "labs.pdf").read_bytes()]}, "options": {"llm": False}})
    assert report["stages"]["lab"]["status"] == "ok"
    assert report["stages"]["history"]["status"] == "skipped"
    assert report["stages"]["radiology"]["status"] == "skipped"


def test_drop_nothing_usable_is_an_error():
    with pytest.raises(service.ServiceError):
        service.handle({"inputs": {"documents": [b"junk"]}, "options": {"llm": False}})


def test_handle_matches_iter_stages_report():
    report = service.handle({"scenario": "case_003", "options": {"llm": False}})
    last = list(service.iter_stages({"scenario": "case_003", "options": {"llm": False}}))[-1]["report"]
    assert {k: v["status"] for k, v in report["stages"].items()} == {k: v["status"] for k, v in last["stages"].items()}
