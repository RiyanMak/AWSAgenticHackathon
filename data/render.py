"""Render patient-portal-style radiology, lab and medical history PDFs from a case spec."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import labs
import network

DISCLAIMER = "SYNTHETIC TEST DOCUMENT. Fictional patient. Hackathon prototype, not medical advice."
PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch
INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
ACCENT = colors.HexColor("#1d4e89")
LAB_ACCENT = colors.HexColor("#2f6f4f")
HIST_ACCENT = colors.HexColor("#5b3f8c")
RULE = colors.HexColor("#cbd2d9")
ALERT = colors.HexColor("#b42318")


def _style(name, font="Helvetica", size=9, leading=11.5, color=INK, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=color, **kw)


STYLES = {
    "facility": _style("facility", "Helvetica-Bold", 14, 17, ACCENT),
    "facility_lab": _style("facility_lab", "Helvetica-Bold", 14, 17, LAB_ACCENT),
    "facility_hist": _style("facility_hist", "Helvetica-Bold", 14, 17, HIST_ACCENT),
    "question": _style("question", "Helvetica-Bold", 9, 11.5, spaceBefore=8, spaceAfter=3),
    "answer": _style("answer", "Courier", 9.5, 12, leftIndent=10),
    "facility_sub": _style("facility_sub", size=8.5, leading=11, color=MUTED),
    "doc_title": _style("doc_title", "Helvetica-Bold", 12, 15, alignment=TA_RIGHT),
    "label": _style("label", "Helvetica-Bold", 7.5, 9, MUTED),
    "value": _style("value"),
    "heading": _style("heading", "Helvetica-Bold", 9.5, 12, spaceBefore=7, spaceAfter=2),
    "body": _style("body"),
    "item": _style("item", leftIndent=14, firstLineIndent=-14, spaceAfter=2),
    "sig": _style("sig", leading=12),
    "cell": _style("cell", size=8.5, leading=10.5),
    "cell_bold": _style("cell_bold", "Helvetica-Bold", 8.5, 10.5),
    "cell_flag": _style("cell_flag", "Helvetica-Bold", 8.5, 10.5, ALERT),
    "cell_head": _style("cell_head", "Helvetica-Bold", 7.5, 9, MUTED),
    "panel": _style("panel", "Helvetica-Bold", 9, 11, colors.white),
}


def fmt_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%m/%d/%Y")


def fmt_datetime(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%m/%d/%Y %I:%M %p")


def age_on(birth_iso: str, on_iso: str) -> int:
    b = date.fromisoformat(birth_iso)
    d = datetime.fromisoformat(on_iso).date()
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def p(text: str, style: str) -> Paragraph:
    return Paragraph(escape(str(text)), STYLES[style])


def patient_name(patient: dict) -> str:
    n = patient["name"][0]
    return f"{n['family'].upper()}, {' '.join(n['given'])}"


def identifier(resource: dict, kind: str) -> str:
    return next(i["value"] for i in resource["identifier"] if i["type"]["text"] == kind)


def _canvas_class(case: dict, section: str):
    """Canvas that draws the portal header/footer with 'Page X of Y'."""
    patient, portal = case["Patient"], case["portal"]
    footer_id = f"{patient_name(patient)}  |  MRN {identifier(patient, 'MRN')}"

    class PortalCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._chrome(total)
                super().showPage()
            super().save()

        def _chrome(self, total: int):
            self.setFillColor(MUTED)
            self.setFont("Helvetica", 7.5)
            top = PAGE_H - 0.45 * inch
            self.drawString(MARGIN, top, f"{portal['name']}  |  {section}")
            self.drawRightString(PAGE_W - MARGIN, top, f"Printed {fmt_datetime(portal['printed'])}")
            self.setStrokeColor(RULE)
            self.setLineWidth(0.5)
            self.line(MARGIN, top - 5, PAGE_W - MARGIN, top - 5)
            bottom = 0.45 * inch
            self.line(MARGIN, bottom + 12, PAGE_W - MARGIN, bottom + 12)
            self.drawString(MARGIN, bottom, footer_id)
            self.drawRightString(PAGE_W - MARGIN, bottom, f"Page {self._pageNumber} of {total}")
            self.setFillColor(ALERT)
            self.setFont("Helvetica-Bold", 7)
            self.drawCentredString(PAGE_W / 2, bottom - 11, DISCLAIMER)

    return PortalCanvas


def _letterhead(name: str, sublines: list[str], title: str, accent, name_style: str) -> Table:
    left = [p(name, name_style)] + [p(s, "facility_sub") for s in sublines]
    t = Table([[left, [p(title, "doc_title")]]], colWidths=[4.3 * inch, 2.7 * inch])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, accent),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    return t


def _info_grid(fields: list[tuple[str, str]]) -> Table:
    if len(fields) % 2:
        fields = fields + [("", "")]
    cells = [[p(lbl, "label"), p(val, "value")] for lbl, val in fields]
    rows = [cells[i] + cells[i + 1] for i in range(0, len(cells), 2)]
    t = Table(rows, colWidths=[1.25 * inch, 2.3 * inch, 1.05 * inch, 2.4 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7fa")),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def _patient_fields(case: dict, on_iso: str) -> list[tuple[str, str]]:
    pt, cov = case["Patient"], case["Coverage"]
    age = age_on(pt["birthDate"], on_iso)
    return [
        ("PATIENT", patient_name(pt)),
        ("DOB / AGE / SEX", f"{fmt_date(pt['birthDate'])}  /  {age}  /  {pt['gender'].capitalize()}"),
        ("MRN", identifier(pt, "MRN")),
    ], [
        ("INSURANCE", f"{cov['payor'][0]['display']}, {cov['class'][0]['name']}"),
        ("MEMBER ID", cov["subscriberId"]),
    ]


def _doc(out: Path, title: str, author: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=0.75 * inch,
        bottomMargin=0.85 * inch,
        title=title,
        author=author,
        subject=DISCLAIMER,
    )


def render_radiology(case: dict, out: Path) -> Path:
    dr, fac = case["DiagnosticReport"], case["facility"]
    head, ins = _patient_fields(case, dr["effectiveDateTime"])
    fields = head + [
        ("ACCESSION", identifier(dr, "Accession")),
        ("ORDERING PROVIDER", dr["basedOn"][0]["display"]),
        ("EXAM DATE", fmt_datetime(dr["effectiveDateTime"])),
        *ins,
        ("REPORT STATUS", dr["status"].capitalize()),
        ("REPORTED", fmt_datetime(dr["issued"])),
    ]
    story = [
        _letterhead(
            fac["name"],
            [fac["address"], f"Phone {fac['phone']}  |  Fax {fac['fax']}"],
            "DIAGNOSTIC IMAGING REPORT",
            ACCENT,
            "facility",
        ),
        Spacer(1, 10),
        _info_grid(fields),
        Spacer(1, 4),
    ]
    for section in dr["_sections"]:
        story.append(p(f"{section['title']}:", "heading"))
        if "text" in section:
            story.append(p(section["text"], "body"))
        for item in section.get("items", []):
            story.append(Paragraph(f"<b>{escape(item['label'])}:</b> {escape(item['text'])}", STYLES["body"]))
            story.append(Spacer(1, 3))
    # Keep impression and signature together so the signature never orphans.
    closing = [p("IMPRESSION:", "heading")]
    closing += [p(line, "item") for line in dr["conclusion"].splitlines()]
    closing += [
        Spacer(1, 6),
        p(f"Electronically signed by: {dr['resultsInterpreter'][0]['display']}", "sig"),
        p(f"Signed: {fmt_datetime(dr['issued'])}", "sig"),
        p(f"Interpreting facility: {dr['performer'][0]['display']}", "sig"),
    ]
    story.append(KeepTogether(closing))
    title = f"{dr['code']['text']} - {fmt_date(dr['effectiveDateTime'])}"
    _doc(out, title, fac["name"]).build(story, canvasmaker=_canvas_class(case, "Test Results: Imaging"))
    return out


def _lab_table(expanded_panels: list[dict]) -> Table:
    widths = [2.6 * inch, 1.2 * inch, 0.55 * inch, 1.35 * inch, 1.3 * inch]
    head = [p(h, "cell_head") for h in ("TEST", "RESULT", "FLAG", "REFERENCE RANGE", "UNITS")]
    rows, style = [head], [
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for panel in expanded_panels:
        r = len(rows)
        rows.append([p(panel["panel"].upper(), "panel"), "", "", "", ""])
        style += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), LAB_ACCENT)]
        for i, row in enumerate(panel["rows"]):
            flagged = bool(row["flag"])
            rows.append(
                [
                    p(row["test"], "cell"),
                    p(row["value"], "cell_flag" if flagged else "cell"),
                    p(row["flag"], "cell_flag"),
                    p(row["ref"], "cell"),
                    p(row["unit"], "cell"),
                ]
            )
            if i % 2:
                style.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor("#f5f7fa")))
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def render_labs(case: dict, out: Path) -> Path:
    sex = case["Patient"]["gender"]
    story = []
    for n, order in enumerate(case["labs"]):
        lab = labs.facility(order["lab"])
        head, ins = _patient_fields(case, order["collected"])
        fields = head + [
            ("ACCESSION", order["accession"]),
            ("ORDERING PROVIDER", order["ordering"]),
            ("COLLECTED", fmt_datetime(order["collected"])),
            ("REPORTED", fmt_datetime(order["reported"])),
            ("FASTING", "Yes" if order.get("fasting") else "No"),
            ("SPECIMEN", order.get("specimen", "Blood")),
            *ins,
        ]
        if n:
            story.append(PageBreak())
        story += [
            _letterhead(
                lab["name"],
                [lab["address"], f"Phone {lab['phone']}  |  CLIA {lab['clia']}"],
                "LABORATORY REPORT",
                LAB_ACCENT,
                "facility_lab",
            ),
            Spacer(1, 10),
            _info_grid(fields),
            Spacer(1, 10),
            _lab_table([labs.expand_panel(pn, sex) for pn in order["panels"]]),
            Spacer(1, 8),
            p("Flags: H = high, L = low, A = abnormal. Reference ranges are lab- and method-specific.", "facility_sub"),
            Spacer(1, 6),
            p(f"Final report. Laboratory director: {lab['director']}", "sig"),
        ]
    first = case["labs"][0]
    title = f"Laboratory results - {fmt_date(first['collected'])}"
    _doc(out, title, labs.facility(first["lab"])["name"]).build(
        story, canvasmaker=_canvas_class(case, "Test Results: Lab")
    )
    return out


def fmt_partial(iso: str) -> str:
    """'2019' -> '2019', '2026-03' -> '03/2026', '2025-11-04' -> '11/04/2025'."""
    parts = iso.split("-")
    return "/".join(parts[1:] + parts[:1])


def _history_table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(h, "cell_head") for h in headers]]
    data += [[p(v, "cell_bold" if i == 0 else "cell") for i, v in enumerate(r)] for r in rows]
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    style += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f7fa")) for i in range(2, len(data), 2)]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _section(title: str, body) -> list:
    bar = Table([[p(title.upper(), "panel")]], colWidths=[7.0 * inch])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), HIST_ACCENT), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    return [Spacer(1, 8), KeepTogether([bar, Spacer(1, 3), body])]


def _pcp_summary(case: dict, h: dict) -> list:
    clinic = network.get_provider(h["provider_id"])
    head, ins = _patient_fields(case, h["printed"])
    fields = head + [
        ("PRIMARY CARE", f"{clinic['clinician']}, {clinic['name']}"),
        ("PRINTED", fmt_datetime(h["printed"])),
        ("LANGUAGE", {"en": "English", "es": "Spanish"}[case["intake"]["preferred_language"]]),
        *ins,
    ]
    none = lambda msg: p(msg, "body")  # noqa: E731
    conditions = (
        _history_table(
            ["PROBLEM", "ICD-10", "ONSET", "STATUS / NOTES"],
            [[c["display"], c["icd10"], fmt_partial(c["onset"]), f"{c['status'].capitalize()}. {c.get('note', '')}".strip()] for c in h["conditions"]],
            [2.2, 0.7, 0.8, 3.3],
        )
        if h["conditions"]
        else none("No active problems.")
    )
    meds = (
        _history_table(
            ["MEDICATION", "DIRECTIONS", "PRESCRIBER"],
            [[m["display"], m["dosage"], m["prescriber"]] for m in h["medications"]],
            [2.5, 2.7, 1.8],
        )
        if h["medications"]
        else none("No active medications.")
    )
    allergies = (
        _history_table(
            ["ALLERGEN", "TYPE", "REACTION", "CRITICALITY", "NOTED"],
            [[a["substance"], a["category"].capitalize(), a["reaction"], a["criticality"].capitalize(), fmt_partial(a["onset"])] for a in h["allergies"]],
            [2.0, 1.0, 2.2, 1.0, 0.8],
        )
        if h["allergies"]
        else none("No known allergies." if h.get("no_known_allergies") else "No allergies on file.")
    )
    procedures = (
        _history_table(["PROCEDURE", "DATE"], [[x["display"], fmt_partial(x["date"])] for x in h["procedures"]], [5.6, 1.4])
        if h["procedures"]
        else none("None on file.")
    )
    family = _history_table(
        ["RELATION", "CONDITION", "AGE AT ONSET"],
        [[f["relation"], f["condition"], str(f.get("onset_age", "Unknown"))] for f in h["family_history"]],
        [1.4, 4.2, 1.4],
    )
    social = _history_table(["", ""], [[k, v] for k, v in h["social_history"].items()], [1.6, 5.4])
    team = _history_table(["ROLE", "CLINICIAN", "ORGANIZATION"], [[m["role"], m["name"], m["organization"]] for m in h["care_team"]], [1.6, 2.2, 3.2])
    story = [
        _letterhead(
            clinic["name"],
            [clinic["address"], f"Phone {clinic['phone']}"],
            "PATIENT HEALTH SUMMARY",
            HIST_ACCENT,
            "facility_hist",
        ),
        Spacer(1, 10),
        _info_grid(fields),
    ]
    for title, body in [
        ("Problem list", conditions),
        ("Current medications", meds),
        ("Allergies and intolerances", allergies),
        ("Surgical and procedure history", procedures),
        ("Family history", family),
        ("Social history", social),
        ("Care team", team),
    ]:
        story += _section(title, body)
    story += [Spacer(1, 10), p(f"Summary generated from the electronic health record of {clinic['name']}. Verify with your care team.", "facility_sub")]
    return story


def _questionnaire(case: dict, h: dict) -> list:
    head, ins = _patient_fields(case, h["completed"])
    fields = head + [("COMPLETED", fmt_datetime(h["completed"])), ("COMPLETED BY", "Patient"), *ins]

    def answers(items: list[str]) -> list:
        return [p(a, "answer") for a in items] or [p("None", "answer")]

    allergies = [a["as_written"] for a in h["allergies"]]
    if h.get("no_known_allergies"):
        allergies = ["No allergies that I know of"]
    qa = [
        ("1. Do you have any ongoing health conditions?", [c["as_written"] for c in h["conditions"]] or ["None that I know of"]),
        ("2. List every medicine you take, including over-the-counter medicines and supplements.", [m["as_written"] for m in h["medications"]]),
        ("3. Are you allergic to any medicines, foods or other things? What happens?", allergies),
        ("4. Past surgeries or procedures (with year).", [x["as_written"] for x in h["procedures"]]),
        ("5. Health problems in your parents, brothers or sisters.", [f["as_written"] for f in h["family_history"]]),
        ("6. Tobacco and alcohol.", [f"{k}: {h['social_history'][k]}" for k in ("Tobacco", "Alcohol")]),
        ("7. Work and home.", [f"{k}: {v}" for k, v in h["social_history"].items() if k not in ("Tobacco", "Alcohol")]),
        ("8. Do you have a regular doctor or see any specialists?", [f"{m['role']}: {m['name']}" for m in h["care_team"]] or ["No"]),
        ("9. Anything else you want us to know?", [h["notes"]] if h.get("notes") else []),
    ]
    story = [
        _letterhead(
            case["portal"]["name"],
            ["New patient intake, submitted online"],
            "PATIENT HEALTH QUESTIONNAIRE",
            HIST_ACCENT,
            "facility_hist",
        ),
        Spacer(1, 10),
        _info_grid(fields),
        Spacer(1, 4),
        p("Answers are entered by the patient and have not been reviewed by a clinician.", "facility_sub"),
    ]
    for q, a in qa:
        story.append(KeepTogether([p(q, "question"), *answers(a)]))
    return story


def render_history(case: dict, out: Path) -> Path:
    h = case["history"]
    if h["source"] == "pcp_record":
        story, title, author, section = _pcp_summary(case, h), "Patient health summary", network.get_provider(h["provider_id"])["name"], "Health Summary"
    else:
        story, title, author, section = _questionnaire(case, h), "Patient health questionnaire", case["portal"]["name"], "Forms: Health Questionnaire"
    _doc(out, title, author).build(story, canvasmaker=_canvas_class(case, section))
    return out
