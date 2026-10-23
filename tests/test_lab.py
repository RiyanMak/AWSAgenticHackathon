"""Lab Agent: exact extraction on the bundled PDFs and deterministic flag/severity rules. No AWS."""

from pathlib import Path

import pytest

from carerelay.agents.lab import FLAG_LETTER, build_row, compare_ranges, rows_to_findings, run_lab_agent
from carerelay.eval import _same_value, expected_lab_rows

DATA = Path(__file__).resolve().parents[1] / "data" / "output"
CASES = sorted(p.name for p in DATA.glob("case_*"))


@pytest.mark.parametrize("case_id", CASES)
def test_rows_and_flags_match_ground_truth(case_id):
    result = run_lab_agent((DATA / case_id / "labs.pdf").read_bytes())
    assert result.status == "ok" and result.extraction_method == "local_text"
    got = [(r.analyte, r.value_text, FLAG_LETTER[r.flag]) for r in result.rows]
    expected = expected_lab_rows(case_id)
    assert len(got) == len(expected)
    for e in expected:
        assert any(g[0] == e[0] and _same_value(g[1], e[1]) and g[2] == e[2] for g in got), e
    assert result.notes == []   # comparator agrees with every printed flag


def flag(value, ref, analyte="LDL Cholesterol"):
    return compare_ranges(build_row(analyte, value, ref_text=ref)).flag


def test_exclusive_and_inclusive_bounds():
    assert flag("200", "<200") == "high"
    assert flag("199", "<200") == "normal"
    assert flag("60", ">=60", "eGFR") == "normal"
    assert flag("59", ">=60", "eGFR") == "low"
    assert flag("<0.01", "<15", "hs-Troponin T") == "normal"


def test_qualitative_results():
    assert flag("Detected", "Not Detected", "Influenza A") == "abnormal"
    assert flag("Not Detected", "Not Detected", "Influenza A") == "normal"
    assert flag("3-5", "0-2", "RBC, urine") == "abnormal"
    assert flag("0-2", "0-5", "WBC, urine") == "normal"


def severity(value, analyte="Potassium", ref="3.5-5.1"):
    row = compare_ranges(build_row(analyte, value, "mmol/L", ref))
    return rows_to_findings([row], "local_text")[0].severity


def test_critical_and_red_flag_limits():
    assert severity("5.6") == "follow_up"
    assert severity("6.3") == "urgent"
    assert severity("6.6") == "red_flag"
    assert severity("2.4") == "red_flag"


def test_unreadable_pdf_requests_reevaluation():
    result = run_lab_agent(b"not a pdf")
    assert result.status == "needs_clinical_reevaluation"
    assert result.error
