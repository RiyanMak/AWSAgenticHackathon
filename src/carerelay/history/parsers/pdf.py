"""Parse the bundled history PDFs (data/output/<case>/history.pdf) into a HistoryProfile.

Two document kinds, detected from the title:

* ``PATIENT HEALTH SUMMARY``   (``pcp_record``): a coded PCP summary with tables (problem list with
  ICD-10 codes, medications, allergies, procedures, family and social history, care team). Parsed
  deterministically from pypdf layout-mode text using the column positions of each table header.
  Codes are read, not inferred (``code_source="document"``).
* ``PATIENT HEALTH QUESTIONNAIRE`` (``patient_questionnaire``): free text typed by the patient, split
  by question number. Conditions and medications go through the coding cascade in ``coding.py``.

Anything else is treated as free text and handed to the intake parser.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..coding import Mode, code_items
from ..risk_flags import derive_risk_flags
from ..schema import CodedItem, HistoryProfile, PatientSummary
from ._specialties import specialties_in_text

SECTION_HEADERS = {
    "PROBLEM LIST": "conditions",
    "CURRENT MEDICATIONS": "medications",
    "ALLERGIES AND INTOLERANCES": "allergies",
    "SURGICAL AND PROCEDURE HISTORY": "procedures",
    "FAMILY HISTORY": "family_history",
    "SOCIAL HISTORY": "social_history",
    "CARE TEAM": "care_team",
}
_FOOTER_RE = re.compile(r"Page \d+ of \d+|SYNTHETIC TEST DOCUMENT|\|\s+(Health Summary|Forms:)|Summary generated from")
_QUESTION_RE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")
_NEG_RE = re.compile(r"^(no|none|n/a|nothing|nkda)\b", re.I)
_DOB_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*/\s*(\d+)\s*/\s*(Female|Male|Other)", re.I)

# Questionnaire question number -> profile section (as rendered by data/render.py)
QUESTION_MAP = {
    1: "conditions",
    2: "medications",
    3: "allergies",
    4: "procedures",
    5: "family_history",
    6: "social_history",
    7: "social_history",
    8: "doctors",
    9: "notes",
}


def extract_layout_text(pdf_path: str | Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages)


def detect_kind(text: str) -> str:
    head = text[:1500].upper()
    if "PATIENT HEALTH SUMMARY" in head:
        return "pcp_record"
    if "QUESTIONNAIRE" in head:
        return "patient_questionnaire"
    return "unknown"


def _iso_date(s: str | None) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    m = re.fullmatch(r"(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return s


# --------------------------------------------------------------------------------------- tables


def _column_starts(header: str) -> list[int]:
    """Start index of every column title in a layout-mode header line (titles separated by 2+ spaces)."""
    return [m.start() for m in re.finditer(r"\S(?:\S| (?=\S))*", header)]


def _cells(line: str, starts: list[int]) -> list[str]:
    out = []
    for i, s in enumerate(starts):
        lo = max(0, s - 1) if i else 0
        hi = max(0, starts[i + 1] - 1) if i + 1 < len(starts) else len(line)
        out.append(line[lo:hi].strip())
    return out


def _table_rows(lines: list[str], key_col: int = 1) -> tuple[list[list[str]], list[str]]:
    """Parse a layout-mode table: first non-blank line is the header. Returns (rows, header_titles).

    A line starts a new row only when both the first column and ``key_col`` (a short field that
    never wraps: code, date, type, clinician) have text. Any other line continues the previous
    row, cell by cell, so wrapped names and wrapped notes on the same line are both appended.
    """
    lines = [ln.rstrip() for ln in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [], []
    header = lines[0]
    starts = _column_starts(header)
    titles = _cells(header, starts)
    key_col = min(key_col, len(starts) - 1)
    rows: list[list[str]] = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cells = _cells(ln, starts)
        if (cells[0] and cells[key_col]) or not rows:
            rows.append(cells)
        else:  # continuation of the previous row (wrapped cells)
            for i, c in enumerate(cells):
                if c:
                    rows[-1][i] = (rows[-1][i] + " " + c).strip()
    return rows, titles


def _two_col_rows(lines: list[str]) -> list[list[str]]:
    """Label/value tables without a header (social history)."""
    rows: list[list[str]] = []
    value_start: int | None = None
    for ln in lines:
        if not ln.strip():
            continue
        if value_start is None:
            m = re.search(r"\S\s{2,}(\S)", ln)
            if not m:
                continue
            value_start = m.start(1)
        label, value = ln[:value_start].strip(), ln[value_start:].strip()
        if label:
            rows.append([label, value])
        elif rows and value:
            rows[-1][1] = (rows[-1][1] + " " + value).strip()
    return rows


def _sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """Split layout text into (header_lines, {section_key: lines}) dropping page chrome."""
    header: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        if _FOOTER_RE.search(raw):
            continue
        key = SECTION_HEADERS.get(raw.strip().upper())
        if key:
            current = key
            sections.setdefault(key, [])
            continue
        if current is None:
            header.append(raw)
        else:
            sections[current].append(raw)
    return header, sections


# --------------------------------------------------------------------------------- PCP summary


def _parse_header(header_lines: list[str], profile: HistoryProfile) -> None:
    text = "\n".join(header_lines)
    m = _DOB_RE.search(text)
    if m:
        profile.patient.birth_date = _iso_date(m.group(1))
        profile.patient.age_years = int(m.group(2))
        profile.patient.gender = m.group(3).lower()
    m = re.search(r"\bMRN\s{2,}(\S+)", text)
    if m:
        profile.patient.patient_id = m.group(1)
    m = re.search(r"LANGUAGE\s{2,}(\S[^\n]*?)(?:\s{2,}|\n|$)", text)
    if m:
        profile.social_history.setdefault("Language", m.group(1).strip())
    m = re.search(r"PRIMARY CARE\s{2,}([^\n]+?)(?:\s{2,}\S|\n|$)", text)
    if m:
        profile.care_team.append(m.group(1).strip())
        profile.known_specialists.append("primary_care")


def _parse_pcp_record(text: str, profile: HistoryProfile, *, mode: Mode, region: str | None, model_id: str | None) -> None:
    header, sections = _sections(text)
    _parse_header(header, profile)
    profile.document_kind = "pcp_record"

    # Problem list
    lines = sections.get("conditions", [])
    if any("no active problems" in ln.lower() for ln in lines):
        pass
    else:
        rows, _ = _table_rows(lines)
        for i, r in enumerate(rows):
            if len(r) < 4 or not r[1]:
                continue
            display, code, onset, status_notes = r[0], r[1], r[2], r[3]
            m = re.match(r"\s*(Active|Resolved|Inactive|Remission|Recurrence)\.?\s*(.*)$", status_notes, re.I)
            status = (m.group(1).lower() if m else "unknown")
            notes = (m.group(2).strip() if m else status_notes.strip()) or None
            profile.conditions.append(
                CodedItem(
                    display=display,
                    code=code,
                    system="icd10cm",
                    status=status,
                    onset=_iso_date(onset),
                    detail=notes,
                    code_source="document",
                    source_ref=f"history.pdf problem_list[{i}]",
                )
            )

    # Medications (no codes printed; cascade can add RxNorm)
    lines = sections.get("medications", [])
    if not any("no active medications" in ln.lower() for ln in lines):
        rows, _ = _table_rows(lines, key_col=2)  # PRESCRIBER column anchors a row
        raw_meds = [r for r in rows if r and r[0]]
        coded = code_items([r[0] for r in raw_meds], "medication", mode=mode, ref="history.pdf medications",
                           warnings=profile.warnings, region=region, model_id=model_id)
        for item, r in zip(coded, raw_meds):
            printed = r[0]
            directions = r[1] if len(r) > 1 else ""
            prescriber = r[2] if len(r) > 2 else ""
            if item.code:  # keep the printed product name as the display; coder's generic goes into detail
                item.detail = f"{directions}; prescriber: {prescriber}; coded as {item.display}".strip("; ")
                item.display = printed
            else:
                item.detail = "; ".join(filter(None, [directions, f"prescriber: {prescriber}" if prescriber else None])) or None
            item.status = "active"
            profile.medications.append(item)

    # Allergies
    lines = sections.get("allergies", [])
    if any("no known" in ln.lower() for ln in lines):
        profile.no_known_allergies = True
    else:
        rows, _ = _table_rows(lines)
        for i, r in enumerate(rows):
            if not r or not r[0]:
                continue
            allergen, typ, reaction, crit, noted = (r + ["", "", "", "", ""])[:5]
            profile.allergies.append(
                CodedItem(
                    display=allergen,
                    status="active",
                    onset=_iso_date(noted),
                    detail="; ".join(filter(None, [reaction or None, f"criticality: {crit.lower()}" if crit else None,
                                                   f"category: {typ.lower()}" if typ else None])) or None,
                    source_ref=f"history.pdf allergies[{i}]",
                )
            )

    # Procedures (past events: they do not imply a current specialist)
    rows, _ = _table_rows(sections.get("procedures", []))
    for i, r in enumerate(rows):
        if r and r[0]:
            profile.procedures.append(
                CodedItem(display=r[0], status="completed", onset=_iso_date(r[1] if len(r) > 1 else None),
                          source_ref=f"history.pdf procedures[{i}]")
            )

    # Family history
    rows, _ = _table_rows(sections.get("family_history", []))
    for i, r in enumerate(rows):
        if len(r) >= 2 and r[1]:
            age = r[2] if len(r) > 2 and r[2] else None
            profile.family_history.append(
                CodedItem(display=r[1], status="family", detail="; ".join(filter(None, [r[0], f"age at onset: {age}" if age else None])),
                          source_ref=f"history.pdf family_history[{i}]")
            )

    # Social history
    for label, value in _two_col_rows(sections.get("social_history", [])):
        profile.social_history[label] = value

    # Care team
    rows, _ = _table_rows(sections.get("care_team", []))
    for r in rows:
        if len(r) >= 2 and r[1]:
            entry = ", ".join(filter(None, [r[1], r[2] if len(r) > 2 else None]))
            if entry not in profile.care_team and not any(r[1] in c for c in profile.care_team):
                profile.care_team.append(entry)
            profile.known_specialists.extend(specialties_in_text(r[0]))


# ------------------------------------------------------------------------------- questionnaire


def _questionnaire_answers(text: str) -> tuple[list[str], dict[int, list[str]]]:
    header: list[str] = []
    answers: dict[int, list[str]] = {}
    current: int | None = None
    for raw in text.splitlines():
        if _FOOTER_RE.search(raw) or not raw.strip():
            continue
        m = _QUESTION_RE.match(raw)
        if m and int(m.group(1)) in QUESTION_MAP:
            current = int(m.group(1))
            answers[current] = []
            continue
        if current is None:
            header.append(raw)
            continue
        line = raw.strip()
        prev = answers[current]
        # a wrapped sentence continues in lower case; a new item starts with a capital/digit
        if prev and (line[:1].islower() or current == 9):
            prev[-1] = f"{prev[-1]} {line}"
        else:
            prev.append(line)
    return header, answers


def _split_reaction(item: str) -> tuple[str, str | None]:
    for sep in (" - ", " – ", ": "):
        if sep in item:
            a, b = item.split(sep, 1)
            return a.strip(), b.strip()
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", item)
    if m and any(w in m.group(2).lower() for w in ("rash", "hives", "swell", "nausea", "anaphyl", "itch", "breath")):
        return m.group(1).strip(), m.group(2).strip()
    return item, None


def _parse_questionnaire(text: str, profile: HistoryProfile, *, mode: Mode, region: str | None, model_id: str | None) -> None:
    header, answers = _questionnaire_answers(text)
    _parse_header(header, profile)
    profile.document_kind = "patient_questionnaire"
    profile.known_specialists = []  # header has no PRIMARY CARE line for questionnaires; reset any false hit

    def items(q: int) -> list[str]:
        return [a for a in answers.get(q, []) if not _NEG_RE.match(a)]

    cond_items, med_items = items(1), items(2)
    profile.conditions = code_items(cond_items, "condition", mode=mode, ref="history.pdf q1", warnings=profile.warnings,
                                    region=region, model_id=model_id)
    profile.medications = code_items(med_items, "medication", mode=mode, ref="history.pdf q2", warnings=profile.warnings,
                                     region=region, model_id=model_id)
    for item in profile.conditions + profile.medications:
        if not item.detail:
            item.detail = f"patient wrote: {item.display}"

    if answers.get(3) and not items(3):
        profile.no_known_allergies = True
    for i, a in enumerate(items(3)):
        substance, reaction = _split_reaction(a)
        profile.allergies.append(CodedItem(display=substance, status="active", detail=reaction,
                                           source_ref=f"history.pdf q3[{i}]"))

    for i, a in enumerate(items(4)):
        m = re.search(r"\b(19|20)\d{2}\b", a)
        profile.procedures.append(CodedItem(display=a, status="completed", onset=m.group(0) if m else None,
                                            source_ref=f"history.pdf q4[{i}]"))

    for i, a in enumerate(items(5)):
        profile.family_history.append(CodedItem(display=a, status="family", source_ref=f"history.pdf q5[{i}]"))

    for q in (6, 7):
        for a in answers.get(q, []):
            if ":" in a:
                k, v = a.split(":", 1)
                profile.social_history[k.strip()] = v.strip()

    for a in items(8):
        profile.care_team.append(a)
        profile.known_specialists.extend(specialties_in_text(a))

    notes = " ".join(answers.get(9, []))
    if notes:
        profile.social_history["Patient notes"] = notes
    profile.warnings.append("Questionnaire answers are patient-reported and unverified")


# ------------------------------------------------------------------------------------- entry


def parse_history_pdf(
    pdf_path: str | Path,
    *,
    mode: Mode = "auto",
    offline: bool = False,
    region: str | None = None,
    model_id: str | None = None,
) -> HistoryProfile:
    """Parse a history PDF. ``offline=True`` forces ``mode="none"`` (no AWS calls)."""
    if offline:
        mode = "none"
    profile = HistoryProfile(source="pdf", patient=PatientSummary())
    try:
        text = extract_layout_text(pdf_path)
    except Exception as exc:  # unreadable file
        profile.source = "degraded"
        profile.warnings.append(f"Could not read PDF: {exc}")
        return profile

    kind = detect_kind(text)
    if kind == "pcp_record":
        _parse_pcp_record(text, profile, mode=mode, region=region, model_id=model_id)
    elif kind == "patient_questionnaire":
        _parse_questionnaire(text, profile, mode=mode, region=region, model_id=model_id)
    else:
        from .intake import parse_intake_text

        fallback = parse_intake_text(text, offline=(mode == "none"), region=region)
        fallback.source = "pdf"
        fallback.document_kind = "unknown"
        fallback.warnings.append("Unrecognised PDF layout; parsed as free text")
        return fallback

    profile.known_specialists = sorted(set(profile.known_specialists))
    profile.risk_flags = derive_risk_flags(profile)
    if not (profile.conditions or profile.medications or profile.allergies or profile.procedures or profile.no_known_allergies):
        profile.warnings.append("No history items found in the PDF")
    return profile
