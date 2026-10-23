"""Radiology Agent: radiology report (PDF or text) -> sections, typed findings and a short summary.

Bedrock reads the report body (patient header stripped) and returns findings with verbatim quotes; every quote
is checked against the source and unverified findings are down-weighted. Without AWS, local term matching with
NegEx-style negation is the fallback. Severity always comes from carerelay.rules, never from the model.

    python -m carerelay.agents.radiology data/output/case_001/radiology.pdf [--aws]
"""

import re
import sys
from pathlib import Path

from carerelay import aws
from carerelay.agents.common import summarize
from carerelay.pdf_text import pdf_pages_text
from carerelay.rules import (CLAUSE_BREAKS, NEGATION_POST, NEGATION_PRE, RADIOLOGY_TERMS, UNCERTAINTY,
                             radiology_severity)
from carerelay.schemas import Finding, ImagingFindings

SECTION_NAMES = ["EXAMINATION", "EXAM", "PROCEDURE", "CLINICAL INDICATION", "CLINICAL HISTORY", "HISTORY",
                 "INDICATION", "REASON FOR EXAM", "COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION", "CONCLUSION"]
_SECTION = re.compile(rf"^\s*({'|'.join(SECTION_NAMES)})\s*:\s*", re.MULTILINE)
_SIGNATURE = re.compile(r"^\s*(Electronically signed|Signed:|Dictated by)", re.MULTILINE)
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x\s*\d+(?:\.\d+)?\s*)*(mm|cm)\b", re.IGNORECASE)
_SEVERITY_ORDER = ["info", "follow_up", "urgent", "red_flag"]
_CERTAINTY_CONFIDENCE = {"definite": 0.9, "probable": 0.75, "possible": 0.6}
SIZED_LABELS = {"Nodule", "Mass", "Lesion", "Cyst", "Stone", "Aortic dilation", "Hematoma"}


def report_body(text: str) -> str:
    """Drop the portal header (name, MRN, DOB, member ID) and signature: the model only needs the report."""
    start = _SECTION.search(text)
    end = _SIGNATURE.search(text, start.start() if start else 0)
    return text[start.start() if start else 0:end.start() if end else len(text)].strip()


def split_sections(text: str) -> dict[str, str]:
    matches = list(_SECTION.finditer(text))
    if not matches:
        return {"FINDINGS": re.sub(r"\s+", " ", text).strip()}
    sections = {}
    for m, nxt in zip(matches, matches[1:] + [None]):
        body = text[m.end():nxt.start() if nxt else len(text)]
        sections[m.group(1).upper()] = re.sub(r"\s+", " ", body).strip()
    return sections


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _strip_negated(text: str) -> str:
    """Remove clauses like 'No intracranial hemorrhage' so severity terms only see positive statements."""
    clauses = re.split(r"(?<=[.;])\s+|,\s+", text)
    return " ".join(c for c in clauses if not re.match(r"^(no|without|negative for|not)\b", c.strip().lower()))


def _size_mm(value: str, unit: str) -> float:
    return float(value) * (10 if unit.lower() == "cm" else 1)


# ---------- Bedrock path ----------

def bedrock_findings(result: dict, body: str, sections: dict[str, str], notes: list[str]) -> list[Finding]:
    source = _norm(body)
    findings = []
    for raw in result.get("findings", []):
        quote = raw.get("evidence_quote", "")
        verified = bool(quote) and _norm(quote) in source
        confidence = _CERTAINTY_CONFIDENCE.get(raw.get("certainty"), 0.6)
        if not verified:
            confidence = 0.4
            notes.append(f"Quote for '{raw.get('label')}' not found verbatim in the report; confidence lowered.")
        size = raw.get("size_mm")
        context = _strip_negated(f"{raw.get('site') or ''}. {quote}. {raw.get('recommendation') or ''}")
        findings.append(Finding(
            id="", source="radiology", label=raw["label"],
            value=raw.get("measurement_text") or (f"{size:g} mm" if size else None),
            evidence=f"\"{quote}\"" + ("" if verified else " [NOT VERIFIED IN SOURCE]"),
            confidence=confidence,
            severity=radiology_severity(raw["label"], context, size, bool(raw.get("recommendation"))),
            specialty_hint=raw.get("specialty_hint"),
            site=raw.get("site"), size_mm=size,
            in_impression=raw.get("in_impression"), answers_indication=raw.get("answers_indication"),
            recommendation=raw.get("recommendation"),
        ))
    return findings


# ---------- local fallback ----------

def _sentences(text: str) -> list[str]:
    # split on sentence ends and on numbered impression items ("1. ... 2. ...")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])|\s+(?=\d+\.\s)", text)
    return [p.strip() for p in parts if p.strip()]


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _clause_around(sentence: str, start: int, end: int) -> tuple[str, str]:
    """Text before and after the term, cut at the nearest clause break."""
    before, after = sentence[:start], sentence[end:]
    for br in CLAUSE_BREAKS:
        if br in before:
            before = before.rsplit(br, 1)[1]
        if br in after:
            after = after.split(br, 1)[0]
    return before, after


def local_mentions(sections: dict[str, str]) -> list[dict]:
    terms = sorted(((p, label) for label, ps in RADIOLOGY_TERMS.items() for p in ps), key=lambda t: -len(t[0]))
    mentions = []
    for section in ("FINDINGS", "IMPRESSION", "CONCLUSION"):
        for sentence in _sentences(sections.get(section, "")):
            low = sentence.lower()
            taken: list[tuple[int, int]] = []
            # longest phrases first, so "tension pneumothorax" wins over "pneumothorax"
            for phrase, label in terms:
                for m in re.finditer(rf"\b{re.escape(phrase)}\b", low):
                    if any(s <= m.start() < e for s, e in taken):
                        continue
                    taken.append((m.start(), m.end()))
                    before, after = _clause_around(low, m.start(), m.end())
                    negated = any(_has_phrase(before, n) for n in NEGATION_PRE) or \
                        any(after.strip().startswith(n) for n in NEGATION_POST)
                    # skip guideline thresholds ("nodule greater than 8 mm"); they are not measurements
                    sizes = sorted((s for s in _SIZE.finditer(sentence)
                                    if not re.search(r"(greater|less|smaller|larger) than\s*$|[<>]\s*$",
                                                     sentence[:s.start()])),
                                   key=lambda s: abs(s.start() - m.start()))
                    mentions.append({
                        "label": label, "negated": negated,
                        "uncertain": any(_has_phrase(low, u) for u in UNCERTAINTY),
                        "size_mm": _size_mm(sizes[0][1], sizes[0][2]) if sizes and label in SIZED_LABELS else None,
                        "section": section, "sentence": sentence,
                    })
    return mentions


def local_findings(mentions: list[dict]) -> list[Finding]:
    by_key: dict[tuple, Finding] = {}
    impression = {(m["label"], m["size_mm"]) for m in mentions if not m["negated"] and m["section"] != "FINDINGS"}
    impression_labels = {label for label, _ in impression}
    for m in (m for m in mentions if not m["negated"]):
        key = (m["label"], m["size_mm"])
        if m["size_mm"] is None:
            # an unsized mention ("the nodule") belongs to the first finding with that label
            key = next((k for k in by_key if k[0] == m["label"]), key)
        # keyword matching misses context a reader would catch, so confidence stays modest
        confidence = 0.5 if m["uncertain"] else 0.65
        evidence = f"{m['section']}: \"{m['sentence']}\""
        if prev := by_key.get(key):
            by_key[key] = prev.model_copy(update={"evidence": f"{prev.evidence} | {evidence}",
                                                  "confidence": max(prev.confidence, confidence)})
            continue
        by_key[key] = Finding(
            id="", source="radiology", label=m["label"],
            value=f"{m['size_mm']:g} mm" if m["size_mm"] else None, evidence=evidence,
            confidence=confidence, size_mm=m["size_mm"],
            severity=radiology_severity(m["label"], _strip_negated(m["sentence"]), m["size_mm"]),
            in_impression=key in impression or (m["size_mm"] is None and m["label"] in impression_labels),
        )
    return list(by_key.values())


# ---------- agent ----------

def _template_summary(findings: list[Finding], impression: str | None) -> str:
    if not findings:
        return "The report describes no abnormal findings." + \
            (f" Radiologist impression: {impression}" if impression else "")
    listed = ", ".join(f"{f.label.lower()}{f' ({f.value})' if f.value else ''}" for f in findings)
    text = f"The radiology report lists {len(findings)} finding(s): {listed}."
    if any(f.severity in ("urgent", "red_flag") for f in findings):
        text += " At least one is marked urgent and needs clinician confirmation first."
    only_findings = [f.label.lower() for f in findings if f.in_impression is False]
    if only_findings:
        text += f" Not repeated in the impression: {', '.join(only_findings)}."
    return text


def report_text_from_bytes(data: bytes, filename: str = "") -> str:
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        return "\n".join(pdf_pages_text(data))
    return data.decode("utf-8", errors="replace")


def run_radiology_agent(report_text: str) -> ImagingFindings:
    notes: list[str] = []
    try:
        body = report_body(report_text)
        if not body:
            return ImagingFindings(status="needs_clinical_reevaluation", error="Empty radiology report.",
                                   summary="The radiology report was empty. Please request clinical re-evaluation.")
        sections = split_sections(body)
        try:
            result = aws.bedrock_read_radiology_report(body)
        except Exception as e:
            notes.append(f"Bedrock radiology extraction failed, used local rules: {type(e).__name__}: {e}")
            result = None
        if result is not None:
            method, findings = "bedrock", bedrock_findings(result, body, sections, notes)
        else:
            method, findings = "local_rules", local_findings(local_mentions(sections))
        findings.sort(key=lambda f: -_SEVERITY_ORDER.index(f.severity))
        findings = [f.model_copy(update={"id": f"rad-{i + 1}"}) for i, f in enumerate(findings)]
        impression = sections.get("IMPRESSION") or sections.get("CONCLUSION")
        summary = summarize("Radiology", findings, _template_summary(findings, impression), notes)
        return ImagingFindings(
            extraction_method=method,
            exam=(result or {}).get("exam") or sections.get("EXAM") or sections.get("EXAMINATION")
            or sections.get("PROCEDURE"),
            indication=(result or {}).get("indication") or sections.get("CLINICAL INDICATION")
            or sections.get("INDICATION") or sections.get("REASON FOR EXAM") or sections.get("CLINICAL HISTORY"),
            sections=sections, findings=findings, summary=summary, notes=notes,
        )
    except Exception as e:
        return ImagingFindings(status="needs_clinical_reevaluation", error=f"{type(e).__name__}: {e}", notes=notes,
                               summary="The radiology report could not be processed. Please request clinical re-evaluation.")


if __name__ == "__main__":
    import os
    if "--aws" in sys.argv:
        os.environ["CARERELAY_USE_AWS"] = "1"
    path = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    result = run_radiology_agent(report_text_from_bytes(path.read_bytes(), path.name))
    print(result.model_dump_json(indent=2, exclude_none=True))
