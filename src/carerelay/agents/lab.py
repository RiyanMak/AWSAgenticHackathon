"""Lab Agent: lab report PDF -> typed rows, deterministic flags, findings and a short summary.

Extraction: the local column parser handles the portal layout in data/output exactly and costs nothing, so it
runs first; Bedrock reads the PDF when the layout is unknown (or when forced with extractor="bedrock").
Flags and severity always come from the deterministic comparator, never from a model.

    python -m carerelay.agents.lab data/output/case_001/labs.pdf [--aws] [--bedrock]
"""

import re
import sys
from datetime import datetime
from pathlib import Path

from carerelay import aws
from carerelay.agents.common import summarize
from carerelay.pdf_text import pdf_pages_text
from carerelay.rules import CRITICAL_LIMITS, LAB_SPECIALTY, RED_FLAG_LIMITS, normalize_analyte
from carerelay.schemas import Finding, LabFindings, LabRow

_NUM = r"-?\d+(?:\.\d+)?"
_HEADER = re.compile(r"^\s*TEST\s{2,}RESULT\s{2,}FLAG\s{2,}REFERENCE RANGE\s{2,}UNITS\s*$")
_COLLECTED = re.compile(r"COLLECTED\s+(\d{2}/\d{2}/\d{4})")
_TABLE_END = re.compile(r"^\s*(Flags:|Final report|Preliminary report)")
_TOKEN = re.compile(r"\S+(?: \S+)*")  # runs of text separated by 2+ spaces
NORMAL_TEXT = {"negative", "not detected", "none seen", "normal", "clear", "yellow", "straw", "pale yellow",
               "nonreactive", "non-reactive"}
FLAG_LETTER = {"low": "L", "critical_low": "L", "high": "H", "critical_high": "H", "abnormal": "A",
               "normal": "", "unknown": ""}


def parse_ref(ref_text: str | None) -> dict:
    ref = (ref_text or "").strip()
    if m := re.fullmatch(rf"({_NUM})\s*[-–]\s*({_NUM})", ref):
        return {"ref_low": float(m[1]), "ref_high": float(m[2])}
    if m := re.fullmatch(rf"<\s*(=?)\s*({_NUM})", ref):
        return {"ref_high": float(m[2]), "ref_high_exclusive": not m[1]}
    if m := re.fullmatch(rf">\s*(=?)\s*({_NUM})", ref):
        return {"ref_low": float(m[2]), "ref_low_exclusive": not m[1]}
    return {}


def build_row(analyte: str, value_text: str, unit: str | None = None, ref_text: str | None = None,
              report_flag: str | None = None, panel: str | None = None, collected: str | None = None,
              page: int | None = None) -> LabRow:
    value_text = value_text.strip()
    num = re.fullmatch(rf"[<>]?=?\s*({_NUM})", value_text)
    return LabRow(
        analyte=analyte.strip(), key=normalize_analyte(analyte),
        value=float(num[1]) if num else None, value_text=value_text,
        unit=(unit or "").strip() or None, ref_text=(ref_text or "").strip() or None,
        report_flag=(report_flag or "").strip() or None, panel=panel, collected=collected, page=page,
        **parse_ref(ref_text),
    )


def _iso(us_date: str) -> str:
    return datetime.strptime(us_date, "%m/%d/%Y").date().isoformat()


def parse_lab_text(pages: list[str]) -> list[LabRow]:
    """Column parser for the portal lab layout: TEST | RESULT | FLAG | REFERENCE RANGE | UNITS."""
    rows = []
    for page_no, text in enumerate(pages, start=1):
        collected = _COLLECTED.search(text)
        collected = _iso(collected[1]) if collected else None
        cols, panel = None, None
        for line in text.splitlines():
            if _HEADER.match(line):
                cols = [line.index(h) for h in ("TEST", "RESULT", "FLAG", "REFERENCE RANGE", "UNITS")]
                continue
            if cols is None or not line.strip():
                continue
            if _TABLE_END.match(line):
                cols = None
                continue
            tokens = list(_TOKEN.finditer(line))
            if len(tokens) == 1 and tokens[0][0].isupper():
                panel = tokens[0][0]
                continue
            cells = ["", "", "", "", ""]
            for t in tokens:
                # the column whose header starts at or just before this token (pypdf can shift a few chars)
                col = max(i for i, start in enumerate(cols) if start <= t.start() + 3)
                cells[col] = f"{cells[col]} {t[0]}".strip()
            if cells[0] and cells[1]:
                rows.append(build_row(cells[0], cells[1], cells[4], cells[3], cells[2], panel, collected, page_no))
    return rows


def compare_ranges(row: LabRow) -> LabRow:
    if row.value is None:
        if row.ref_text is None:
            flag = "unknown"
        elif row.value_text.lower() == row.ref_text.lower() or row.value_text.lower() in NORMAL_TEXT:
            flag = "normal"
        elif (m := re.fullmatch(rf"({_NUM})\s*-\s*({_NUM})", row.value_text)) and row.ref_high is not None \
                and float(m[2]) <= row.ref_high and float(m[1]) >= (row.ref_low or 0):
            flag = "normal"     # "0-2" /hpf inside "0-5"
        else:
            flag = "abnormal"   # "Detected", "Trace", "3-5" /hpf against "0-2"
        return row.model_copy(update={"flag": flag})

    v, prefix = row.value, row.value_text[:1]
    crit_lo, crit_hi = CRITICAL_LIMITS.get(row.key, (None, None))
    below = row.ref_low is not None and (v < row.ref_low or (row.ref_low_exclusive and v == row.ref_low))
    above = row.ref_high is not None and (v > row.ref_high or (row.ref_high_exclusive and v == row.ref_high))
    if crit_lo is not None and v <= crit_lo and prefix != ">":
        flag = "critical_low"
    elif crit_hi is not None and v >= crit_hi and prefix != "<":
        flag = "critical_high"
    elif below and prefix != ">":
        flag = "low"
    elif above and prefix != "<":
        flag = "high"
    elif row.ref_low is None and row.ref_high is None:
        flag = "unknown"
    else:
        flag = "normal"
    return row.model_copy(update={"flag": flag})


def _severity(row: LabRow) -> str:
    if row.value is not None:
        rf_lo, rf_hi = RED_FLAG_LIMITS.get(row.key, (None, None))
        if (rf_lo is not None and row.value <= rf_lo) or (rf_hi is not None and row.value >= rf_hi):
            return "red_flag"
    if row.flag in ("critical_low", "critical_high"):
        return "urgent"
    return "follow_up" if row.key in LAB_SPECIALTY else "info"


def rows_to_findings(rows: list[LabRow], method: str) -> list[Finding]:
    confidence = {"bedrock": 0.85, "textract": 0.9, "local_text": 0.95}[method]
    findings = []
    for row in rows:
        if row.flag in ("normal", "unknown"):
            continue
        findings.append(Finding(
            id=f"lab-{len(findings) + 1}",
            source="lab",
            label=row.analyte,
            value=f"{row.value_text} {row.unit or ''}".strip(),
            evidence=f"page {row.page}, {row.panel or 'lab'}: {row.analyte} {row.value_text} {row.unit or ''} "
                     f"(ref {row.ref_text or 'n/a'}, printed flag {row.report_flag or 'none'}) -> {row.flag}",
            # unknown analytes get lower confidence: no table entry to sanity-check against
            confidence=confidence if row.key else round(confidence - 0.15, 2),
            severity=_severity(row),
            specialty_hint=LAB_SPECIALTY.get(row.key, "primary_care"),
            panel=row.panel,
            observed_at=row.collected,
        ))
    return findings


def flag_disagreements(rows: list[LabRow]) -> list[str]:
    """Our comparator vs the flag the lab printed; a mismatch usually means an extraction error."""
    return [f"{r.analyte} {r.value_text}: lab printed '{r.report_flag or ''}', comparator says {r.flag}"
            for r in rows if r.flag != "unknown" and (r.report_flag or "") != FLAG_LETTER[r.flag]]


def _template_summary(rows: list[LabRow], findings: list[Finding]) -> str:
    if not findings:
        return f"{len(rows)} lab results were read and all are within the reference ranges printed on the report."
    flagged = "; ".join(f"{f.label} {f.value}" + (f" (from {f.observed_at})" if f.observed_at else "")
                        for f in findings)
    text = f"{len(rows)} lab results were read and {len(findings)} are outside the reference range: {flagged}."
    urgent = [f for f in findings if f.severity in ("urgent", "red_flag")]
    if urgent:
        text += f" {len(urgent)} crossed a critical limit and need clinician confirmation before anything else."
    return text


def _bedrock_rows(pdf_bytes: bytes, notes: list[str], use_aws: bool | None) -> list[LabRow] | None:
    try:
        raw = aws.bedrock_extract_lab_rows(pdf_bytes, enabled=use_aws)
    except Exception as e:
        notes.append(f"Bedrock lab extraction failed: {type(e).__name__}: {e}")
        return None
    if raw is None:
        return None
    return [build_row(r["analyte"], r["value_text"], r.get("unit"), r.get("ref_text"), r.get("report_flag"),
                      r.get("panel"), r.get("collected"), r.get("page")) for r in raw if r.get("value_text")]


def run_lab_agent(pdf_bytes: bytes, extractor: str = "auto", use_aws: bool | None = None) -> LabFindings:
    """extractor: "auto" (local parser, Bedrock if it finds nothing), "local" or "bedrock".
    use_aws: None follows CARERELAY_USE_AWS; True/False overrides it for this call."""
    notes: list[str] = []
    try:
        rows, method = None, None
        if extractor in ("auto", "local"):
            rows, method = parse_lab_text(pdf_pages_text(pdf_bytes)), "local_text"
            if not rows and extractor == "auto":
                notes.append("Local parser found no lab table; trying Bedrock.")
        if not rows and extractor in ("auto", "bedrock"):
            rows, method = _bedrock_rows(pdf_bytes, notes, use_aws), "bedrock"
            if rows is None and extractor == "bedrock":
                notes.append("Bedrock is off (set CARERELAY_USE_AWS=1); used the local parser.")
                rows, method = parse_lab_text(pdf_pages_text(pdf_bytes)), "local_text"
        if not rows:
            return LabFindings(status="needs_clinical_reevaluation", extraction_method=method, notes=notes,
                               error="No lab rows could be read from the PDF.",
                               summary="The lab report could not be read. Please request clinical re-evaluation.")
        rows = [compare_ranges(r) for r in rows]
        notes += flag_disagreements(rows)
        findings = rows_to_findings(rows, method)
        summary = summarize("Lab", findings, _template_summary(rows, findings), notes, use_aws)
        return LabFindings(extraction_method=method, rows=rows, findings=findings, summary=summary, notes=notes)
    except Exception as e:
        return LabFindings(status="needs_clinical_reevaluation", error=f"{type(e).__name__}: {e}", notes=notes,
                           summary="The lab report could not be processed. Please request clinical re-evaluation.")


if __name__ == "__main__":
    import os
    if "--aws" in sys.argv:
        os.environ["CARERELAY_USE_AWS"] = "1"
    path = next(a for a in sys.argv[1:] if not a.startswith("--"))
    result = run_lab_agent(Path(path).read_bytes(), "bedrock" if "--bedrock" in sys.argv else "auto")
    print(result.model_dump_json(indent=2, exclude_none=True))
