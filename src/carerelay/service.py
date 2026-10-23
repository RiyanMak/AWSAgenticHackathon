"""Single entry point every deployment lane calls: ``service.handle(request) -> report``.

The three lanes in docs/AWS_INFRASTRUCTURE.md (Lambda Function URL, AgentCore Runtime, Streamlit)
only differ in how they receive the request and where they put the report. They all call this.

Request shape (JSON):

    {"scenario": "case_001"}                                   # bundled synthetic case
    {"inputs": {"history_pdf": "<path or base64>",             # or explicit inputs
                "labs_pdf": "...", "radiology_pdf": "...",
                "intake": {...}, "coverage": {...FHIR Coverage...},
                "patient": {"address": [{"postalCode": "78745"}], ...}},
     "options": {"llm": true, "model_id": "...", "region": "...", "human_confirmed": false}}

Report shape: see ``build_report``. Flow: History, Lab and Radiology run in parallel -> Summarize (CaseRecord)
-> Wellness and Next Steps (with the Insurance Agent). Red-flag or urgent findings pause Next Steps until the
request carries ``options.human_confirmed`` (docs/SAFETY.md guardrail 4); Wellness applies its own gate.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .agents.lab import run_lab_agent
from .agents.radiology import report_text_from_bytes, run_radiology_agent
from .history import run_history_agent
from .history.schema import HistoryProfile
from .next_steps import NextStepsPlan, patient_context, run_next_steps
from .schemas import CaseRecord, Finding, ImagingFindings, LabFindings
from .summarize import run_summarize, to_next_steps_request

DISCLAIMER = (
    "CareRelay is a hackathon prototype that uses synthetic or public data. It is not a clinical "
    "system and does not provide medical advice, diagnosis or treatment. Findings must be reviewed "
    "by a licensed clinician. In an emergency call your local emergency number."
)

STAGES = ["history", "lab", "radiology", "summarize", "wellness", "next_steps"]
_SCENARIO_RE = re.compile(r"\bcase_\d{3}\b")


class ServiceError(ValueError):
    """Bad request (unknown scenario, missing inputs). Lanes map this to HTTP 400."""


# ------------------------------------------------------------------------------------ data dir


def find_data_dir() -> Path:
    """``CARERELAY_DATA_DIR`` env, else the repo's ``data/`` found by walking up from this file,
    else ``/var/task/data`` (Lambda image) or ``/app/data`` (AgentCore image)."""
    env = os.environ.get("CARERELAY_DATA_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "cases").is_dir():
            return parent / "data"
    for candidate in (Path("/var/task/data"), Path("/app/data")):
        if (candidate / "cases").is_dir():
            return candidate
    raise ServiceError("Bundled data directory not found; set CARERELAY_DATA_DIR")


def list_scenarios() -> list[dict[str, Any]]:
    data = find_data_dir()
    out = []
    for path in sorted((data / "cases").glob("case_*.json")):
        case = json.loads(path.read_text())
        pt = case["Patient"]
        out.append(
            {
                "case_id": case["case_id"],
                "exam": case["DiagnosticReport"]["code"]["text"],
                "plan": case["Coverage"]["class"][0]["value"],
                "patient": f"{pt['gender']}, born {pt['birthDate']}, {pt['address'][0]['postalCode']}",
                "history_source": case["history"]["source"],
            }
        )
    return out


def load_scenario(case_id: str) -> dict[str, Any]:
    """Return the inputs a patient would upload for a bundled case (never the answer key)."""
    data = find_data_dir()
    case_path = data / "cases" / f"{case_id}.json"
    out_dir = data / "output" / case_id
    if not case_path.exists() or not out_dir.is_dir():
        raise ServiceError(f"Unknown scenario {case_id!r}; available: {[s['case_id'] for s in list_scenarios()]}")
    case = json.loads(case_path.read_text())
    return {
        "case_id": case_id,
        "history_pdf": str(out_dir / "history.pdf"),
        "labs_pdf": str(out_dir / "labs.pdf"),
        "radiology_pdf": str(out_dir / "radiology.pdf"),
        "intake": case["intake"],
        "coverage": case["Coverage"],
        "patient": {k: case["Patient"][k] for k in ("gender", "birthDate", "address") if k in case["Patient"]},
    }


# ------------------------------------------------------------------------------------- inputs


def _looks_like_path(value: str) -> bool:
    """Short, newline-free strings that exist on disk (or start with '/') are paths; base64 blobs are not."""
    if len(value) > 1024 or "\n" in value:
        return False
    if value.startswith("/"):
        return True
    try:
        return Path(value).exists()
    except OSError:
        return False


def _materialize(value: str | bytes | None, suffix: str, workdir: Path) -> str | None:
    """Accept a file path, raw bytes, or base64 text; return a local path."""
    if value is None:
        return None
    if isinstance(value, bytes):
        path = workdir / f"input_{suffix}"
        path.write_bytes(value)
        return str(path)
    if isinstance(value, str) and _looks_like_path(value):
        if not Path(value).exists():
            raise ServiceError(f"Input file not found: {value}")
        return value
    if isinstance(value, str):
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(f"Input for {suffix} is neither a path nor base64: {exc}") from exc
        path = workdir / f"input_{suffix}"
        path.write_bytes(raw)
        return str(path)
    raise ServiceError(f"Unsupported input type for {suffix}: {type(value).__name__}")


def _intake_text(intake: dict[str, Any] | str | None) -> str | None:
    """Turn the intake answers into the 'Header: items' text the History Agent's intake parser reads."""
    if not intake:
        return None
    if isinstance(intake, str):
        return intake
    lines = []
    if intake.get("medications"):
        lines.append("Medications: " + ", ".join(intake["medications"]))
    if intake.get("history"):
        lines.append("Conditions: " + "; ".join(intake["history"]))
    if intake.get("allergies"):
        lines.append("Allergies: " + ", ".join(intake["allergies"]))
    return "\n".join(lines) or None


# ------------------------------------------------------------------------------------- report


def _history_markdown(p: HistoryProfile) -> str:
    def items(xs, fmt):
        return "\n".join(f"- {fmt(x)}" for x in xs) if xs else "- none recorded"

    md = [
        "## Medical history",
        p.summary or "_Summary not generated (parse-only run)._",
        "",
        f"**Source:** {p.source}" + (f" ({p.document_kind})" if p.document_kind else ""),
        f"**Risk flags:** {', '.join(p.risk_flags) or 'none'}",
        "",
        "### Conditions",
        items(p.conditions, lambda c: f"{c.display}" + (f" ({c.system.upper()} {c.code})" if c.code else "") + (f", {c.status}" if c.status else "")),
        "### Medications",
        items(p.active_medications(), lambda m: f"{m.display}" + (f": {m.detail}" if m.detail else "")),
        "### Allergies",
        ("- No known allergies" if p.no_known_allergies and not p.allergies else items(p.allergies, lambda a: f"{a.display}" + (f" ({a.detail})" if a.detail else ""))),
        "### Procedures",
        items(p.procedures, lambda x: f"{x.display}" + (f", {x.onset}" if x.onset else "")),
    ]
    if p.known_specialists:
        md += ["", f"**Already sees:** {', '.join(p.known_specialists)}"]
    if p.clinician_notes:
        md += ["", "### Notes for the reviewing clinician"] + [f"- {n}" for n in p.clinician_notes]
    if p.warnings:
        md += ["", "### Warnings"] + [f"- {w}" for w in p.warnings]
    return "\n".join(md)


def _findings_md(findings: list[Finding]) -> str:
    if not findings:
        return "- none"
    return "\n".join(
        f"- **{f.severity}** {f.label}{f' {f.value}' if f.value else ''}"
        + (" _(findings section only, not in impression)_" if f.in_impression is False else "")
        + (f" (from {f.observed_at})" if f.observed_at else "")
        + (f", follow-up: {f.specialty_hint}" if f.specialty_hint else "")
        for f in findings
    )


def _lab_markdown(r: LabFindings) -> str:
    return "\n".join(["## Lab results", r.summary, "", f"**Rows read:** {len(r.rows)} ({r.extraction_method})",
                      "### Outside reference range", _findings_md(r.findings)])


def _radiology_markdown(r: ImagingFindings) -> str:
    return "\n".join(["## Radiology", r.summary, "", f"**Exam:** {r.exam}", f"**Indication:** {r.indication}",
                      "### Findings", _findings_md(r.findings)])


def _lab_stage(path: str, use_llm: bool) -> tuple[dict[str, Any], LabFindings]:
    r = run_lab_agent(Path(path).read_bytes(), use_aws=use_llm)
    return {"status": r.status, "result": r.model_dump(exclude_none=True), "markdown": _lab_markdown(r)}, r


def _radiology_stage(path: str, use_llm: bool) -> tuple[dict[str, Any], ImagingFindings]:
    r = run_radiology_agent(report_text_from_bytes(Path(path).read_bytes(), path), use_aws=use_llm)
    return {"status": r.status, "result": r.model_dump(exclude_none=True), "markdown": _radiology_markdown(r)}, r


def _summarize_markdown(r: CaseRecord) -> str:
    lines = ["## Summary", r.summary, "", "### Findings"]
    for f in r.findings:
        tag = f"expected ({f.explained_by})" if not f.incidental else "incidental"
        lines.append(f"- **{r.triage[f.id]}** {f.label}{f' {f.value}' if f.value else ''}: {tag}")
    if not r.findings:
        lines.append("- none")
    lines += ["", "### Incidental ledger"]
    lines += [f"- {e.label} ({e.source}, {e.triage}): {e.status}" for e in r.ledger] or ["- empty"]
    if r.needs_confirmation:
        lines += ["", "**Needs clinician confirmation before any care action:** " + ", ".join(r.needs_confirmation)]
    if r.critic_notes or r.gaps:
        lines += ["", "### Critic and gaps"] + [f"- {n}" for n in r.critic_notes + r.gaps]
    return "\n".join(lines)


def _next_steps_markdown(p: NextStepsPlan) -> str:
    lines = ["## Next steps", p.summary, ""]
    if p.coverage:
        lines += [f"**Coverage:** {p.coverage.summary}", ""]
    for s in p.steps:
        if s.status == "proposed":
            where = f"{s.provider_name}, {s.distance_miles} mi" + ("" if s.in_network else ", out of network")
            lines.append(f"- **{s.triage}** {s.service_name}: {s.slot_start.replace('T', ' ')} at {where}, "
                         f"est. ${s.patient_pays:,.2f} ({'; '.join(s.reasons)})")
        else:
            lines.append(f"- {s.service_name}: {s.status.replace('_', ' ')} ({'; '.join(s.reasons)})")
    lines.append(f"\n**Estimated total:** ${p.total_patient_pays:,.2f}. All appointments are proposed only.")
    lines += [f"- {n}" for n in p.caregiver_notes]
    return "\n".join(lines)


def _run_downstream(stages: dict[str, dict[str, Any]], profile: HistoryProfile | None, lab: LabFindings | None,
                    rad: ImagingFindings | None, inputs: dict[str, Any], options: dict[str, Any], use_llm: bool) -> None:
    """Summarize -> Wellness and Next Steps. Each stage fails soft (guardrail 2)."""
    if lab is None and rad is None:
        for name in ("summarize", "wellness", "next_steps"):
            stages[name] = {"status": "skipped", "reason": "no lab or radiology results to summarize"}
        return
    model = {"model_id": options.get("model_id"), "region": options.get("region")}
    try:
        record = run_summarize(profile, lab, rad, use_llm=use_llm,
                               human_confirmed=bool(options.get("human_confirmed")), **model)
        stages["summarize"] = {"status": "ok", "case_record": record.model_dump(mode="json"),
                               "markdown": _summarize_markdown(record)}
    except Exception as exc:  # noqa: BLE001
        for name in ("summarize", "wellness", "next_steps"):
            stages[name] = {"status": "needs_clinical_reevaluation", "error": f"summarize: {type(exc).__name__}: {exc}"}
        return

    try:
        from .wellness.agent import make_wellness_agent, run_wellness

        agent = None
        if use_llm:
            from .aws import make_strands_model
            agent = make_wellness_agent(model=make_strands_model(**model))
        out = run_wellness(record, agent=agent, use_model=use_llm)
        stages["wellness"] = {"status": "ok", "result": out, "markdown": "## Wellness while you wait\n" + out["text"]}
    except Exception as exc:  # noqa: BLE001
        stages["wellness"] = {"status": "needs_clinical_reevaluation", "error": f"{type(exc).__name__}: {exc}"}

    if record.needs_confirmation:
        labels = [f.label for f in record.findings if f.id in record.needs_confirmation]
        stages["next_steps"] = {
            "status": "awaiting_confirmation", "needs_confirmation": record.needs_confirmation,
            "markdown": "## Next steps\nUrgent results need a clinician to confirm first: " + ", ".join(labels)
                        + ". Follow-up planning resumes once confirmed (options.human_confirmed).",
        }
        return
    if not inputs.get("coverage") or not (inputs.get("patient") or {}).get("address"):
        stages["next_steps"] = {"status": "skipped", "reason": "no coverage or patient address provided"}
        return
    try:
        ctx = patient_context(inputs.get("intake") if isinstance(inputs.get("intake"), dict) else None,
                              inputs["patient"], profile.care_team if profile else [])
        plan = run_next_steps(to_next_steps_request(record, inputs["coverage"], ctx), use_llm=use_llm, **model)
        stages["next_steps"] = {"status": plan.status, "plan": plan.model_dump(mode="json"),
                                "markdown": _next_steps_markdown(plan)}
    except Exception as exc:  # noqa: BLE001
        stages["next_steps"] = {"status": "needs_clinical_reevaluation", "error": f"{type(exc).__name__}: {exc}"}


def build_report(case_id: str | None, stages: dict[str, dict[str, Any]], started: float) -> dict[str, Any]:
    sections = ["# CareRelay report", f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} for {case_id or 'uploaded inputs'}._", ""]
    for name in STAGES:
        st = stages.get(name, {"status": "not_implemented"})
        if st["status"] == "ok" and st.get("markdown"):
            sections.append(st["markdown"])
        else:
            sections.append(f"## {name.replace('_', ' ').title()}\n_Stage {st['status']}._")
        sections.append("")
    sections.append(f"> {DISCLAIMER}")
    return {
        "version": __version__,
        "case_id": case_id,
        "stages": stages,
        "report": {"markdown": "\n".join(sections)},
        "disclaimer": DISCLAIMER,
        "elapsed_seconds": round(time.time() - started, 2),
    }


# -------------------------------------------------------------------------------------- handle


def handle(request: dict[str, Any] | str | None) -> dict[str, Any]:
    """Run the CareRelay pipeline for one request. Raises ServiceError on bad input."""
    started = time.time()
    if isinstance(request, str):
        request = _request_from_text(request)
    request = request or {}
    options = request.get("options") or {}
    use_llm = bool(options.get("llm", True))

    case_id = request.get("scenario")
    inputs: dict[str, Any] = dict(request.get("inputs") or {})
    if case_id:
        inputs = {**load_scenario(case_id), **inputs}
    elif not inputs:
        raise ServiceError("Request needs 'scenario' or 'inputs'")

    workdir = Path(tempfile.mkdtemp(prefix="carerelay_"))
    history_pdf = _materialize(inputs.get("history_pdf"), "history.pdf", workdir)
    intake_text = _intake_text(inputs.get("intake"))
    labs_pdf = _materialize(inputs.get("labs_pdf"), "labs.pdf", workdir)
    radiology_pdf = _materialize(inputs.get("radiology_pdf"), "radiology.pdf", workdir)
    stages: dict[str, dict[str, Any]] = {}

    # Stages: lab and radiology run in the background while history runs below
    pool = ThreadPoolExecutor(max_workers=2)
    lab_future = pool.submit(_lab_stage, labs_pdf, use_llm) if labs_pdf else None
    rad_future = pool.submit(_radiology_stage, radiology_pdf, use_llm) if radiology_pdf else None

    # Stage: history (implemented)
    profile: HistoryProfile | None = None
    if history_pdf or intake_text:
        try:
            profile = run_history_agent(
                history_pdf=history_pdf,
                intake_text=intake_text,
                use_llm=use_llm,
                model_id=options.get("model_id"),
                region=options.get("region"),
            )
            stages["history"] = {
                "status": "ok",
                "profile": profile.model_dump(),
                "markdown": _history_markdown(profile),
            }
        except Exception as exc:  # noqa: BLE001  (guardrail 2: never crash the pipeline)
            stages["history"] = {"status": "needs_clinical_reevaluation", "error": f"{type(exc).__name__}: {exc}"}
    else:
        stages["history"] = {"status": "skipped", "reason": "no history_pdf or intake provided"}

    results: dict[str, Any] = {}
    for name, future in (("lab", lab_future), ("radiology", rad_future)):
        # the agents already turn their own failures into needs_clinical_reevaluation; this is a backstop
        try:
            if future:
                stages[name], results[name] = future.result()
            else:
                stages[name] = {"status": "skipped", "reason": f"no {name} PDF provided"}
        except Exception as exc:  # noqa: BLE001
            stages[name] = {"status": "needs_clinical_reevaluation", "error": f"{type(exc).__name__}: {exc}"}
    pool.shutdown()

    profile_obj = profile if stages["history"]["status"] == "ok" else None
    _run_downstream(stages, profile_obj, results.get("lab"), results.get("radiology"), inputs, options, use_llm)

    return build_report(case_id, stages, started)


def _request_from_text(text: str) -> dict[str, Any]:
    """Free-text prompts (AgentCore lane): pick a scenario mentioned in the prompt, else JSON."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    m = _SCENARIO_RE.search(text)
    if m:
        return {"scenario": m.group(0), "options": {"llm": "no llm" not in text.lower() and "parse only" not in text.lower()}}
    raise ServiceError("Prompt must name a scenario like case_001 or be a JSON request")
