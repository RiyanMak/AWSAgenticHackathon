"""CareRelay patient portal (Shiny for Python, Course theme).

    ./run.sh                                  # or: .venv/bin/shiny run src/carerelay/ui/app.py

Drop the PDFs from your portals (sorted by content), or load a sample patient; CareRelay runs the
agent team through service.handle() (live on Amazon Bedrock when credentials allow) and draws it as an
agent course with a handoff log, then shows the plain-language result. See docs/FRONTEND.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path

from shiny import App, reactive, render, req, ui

from carerelay import aws, service
from carerelay.network import net
from carerelay.ui import pipeline, views

WWW = Path(__file__).parent / "www"
KIND_LABEL = {"history": "Health summary", "labs": "Lab results", "radiology": "Imaging report"}
SLOTS = ("history", "labs", "radiology")

# ------------------------------------------------------------------ Bedrock check (once, in background)

BEDROCK: dict = {"state": "checking", "detail": ""}


def _check_bedrock() -> None:
    try:
        import boto3

        boto3.client("sts", region_name=aws.AWS_REGION).get_caller_identity()
        aws._bedrock().converse(modelId=aws.BEDROCK_MODEL_ID, messages=[{"role": "user", "content": [{"text": "Reply OK"}]}],
                                inferenceConfig={"maxTokens": 5})
        BEDROCK.update(state="ok", detail=f"{aws.BEDROCK_MODEL_ID} · {aws.AWS_REGION}")
    except Exception as exc:  # noqa: BLE001
        BEDROCK.update(state="off", detail=f"{type(exc).__name__}: rules-only mode")


_CHECK_LOCK = threading.Lock()


def _ensure_bedrock_check() -> None:
    """Start the one-time check when the first browser session opens (not at import, so tests stay offline)."""
    with _CHECK_LOCK:
        if BEDROCK.get("started"):
            return
        BEDROCK["started"] = True
    if os.environ.get("CARERELAY_SKIP_BEDROCK_CHECK") == "1":
        BEDROCK.update(state="off", detail="check skipped")
        return
    threading.Thread(target=_check_bedrock, daemon=True).start()


def _plans() -> dict[str, str]:
    return {p["plan_id"]: p["name"] for p in net().plans().values()}


def _samples() -> dict[str, str]:
    return {"": "Choose a sample patient"} | {s["case_id"]: f"{s['case_id']} · {s['exam']}" for s in service.list_scenarios()}


# ------------------------------------------------------------------------------------------ layout

app_ui = ui.page_fillable(
    ui.head_content(
        ui.tags.link(rel="stylesheet", href="tokens.css"),
        ui.tags.link(rel="stylesheet", href="course.css"),
        ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
    ),
    ui.tags.header(
        ui.div("CareRelay", class_="brand"),
        ui.span("Synthetic data · prototype · not medical advice", class_="synth"),
        ui.output_ui("bedrock_status"),
        class_="top",
    ),
    ui.div(
        ui.tags.aside(
            ui.h2("Your reports"),
            ui.input_file("docs", None, multiple=True, accept=[".pdf"], button_label="Choose PDFs",
                          placeholder="or drop here", width="100%"),
            ui.output_ui("doc_list"),
            ui.div(
                ui.input_select("sample", None, _samples(), width="100%"),
                ui.input_action_button("load", "Load sample records", class_="btn-quiet"),
                class_="sample-row",
            ),
            ui.output_ui("insurance"),
            ui.input_text_area("intake", "Anything else we should know?", rows=3, width="100%",
                               placeholder="Current medicines, allergies, conditions"),
            ui.input_switch("llm", "Use Amazon Bedrock", value=True),
            ui.accordion(
                ui.accordion_panel(
                    "Advanced",
                    ui.input_text("model_id", "Bedrock model id", value=aws.BEDROCK_MODEL_ID, width="100%"),
                    ui.input_switch("demo", "Fill any unbuilt agent with demo data", value=False),
                ),
                open=False,
            ),
            ui.input_task_button("run", "Share with CareRelay", label_busy="Care team working..."),
            class_="inputs",
        ),
        ui.tags.main(
            ui.tags.section(
                ui.div(ui.h2("Your care team"), ui.output_ui("clock"), class_="panel-head"),
                ui.div(ui.output_ui("course"), ui.output_ui("log"), class_="course-row"),
                ui.output_ui("tasks"),
                class_="panel",
            ),
            ui.tags.section(ui.output_ui("results"), ui.output_ui("downloads"), class_="panel results"),
            ui.tags.footer(service.DISCLAIMER),
        ),
        class_="layout",
    ),
    padding=0,
    gap=0,
    title="CareRelay",
)


# ------------------------------------------------------------------------------------------ server


def server(input, output, session):
    _ensure_bedrock_check()
    events: reactive.Value[list] = reactive.Value([])
    docs: reactive.Value[list] = reactive.Value([])  # [(name, bytes, kind)]
    sample_case: reactive.Value[str | None] = reactive.Value(None)
    confirmed = reactive.Value(False)
    started = reactive.Value(0.0)
    last_request: reactive.Value[dict | None] = reactive.Value(None)
    inbox: queue.Queue = queue.Queue()

    # -- inputs
    @reactive.effect
    def _bedrock_default():
        if BEDROCK["state"] == "checking":
            reactive.invalidate_later(1)
            return
        with reactive.isolate():
            ui.update_switch("llm", value=BEDROCK["state"] == "ok")

    @render.ui
    def bedrock_status():
        if BEDROCK["state"] == "checking":
            reactive.invalidate_later(1)
        label = {"checking": "Checking Amazon Bedrock...", "ok": "Amazon Bedrock connected", "off": "Bedrock unavailable"}[BEDROCK["state"]]
        return ui.span(ui.span(class_=f"dot {BEDROCK['state']}"), label, ui.span(BEDROCK["detail"], class_="detail"), class_="bedrock")

    @reactive.effect
    @reactive.event(input.docs)
    def _uploaded():
        files = input.docs() or []
        docs.set([(f["name"], Path(f["datapath"]).read_bytes(), None) for f in files])
        sample_case.set(None)

    @reactive.effect
    @reactive.event(input.load)
    def _load_sample():
        case_id = input.sample()
        req(case_id)
        sc = service.load_scenario(case_id)
        docs.set([(Path(sc[k]).name, Path(sc[k]).read_bytes(), None) for k in ("history_pdf", "labs_pdf", "radiology_pdf")])
        sample_case.set(case_id)
        ui.update_text_area("intake", value=_sample_intake_text(case_id))

    @reactive.calc
    def sorted_docs() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {k: [] for k in (*SLOTS, "unknown")}
        for name, raw, _ in docs():
            out[service.classify_pdf(raw)].append(name)
        return out

    @render.ui
    def doc_list():
        found = sorted_docs()
        rows = []
        for i, kind in enumerate(SLOTS, start=1):
            names = found[kind]
            rows.append(ui.tags.li(
                ui.span(str(i), class_="slot-n"), ui.tags.b(KIND_LABEL[kind]),
                ui.span(names[0] if names else "not added", class_="slot-file"),
                class_="slot on" if names else "slot",
            ))
        extra = [ui.tags.li(f"Not recognised: {n}", class_="slot-warn") for n in found["unknown"]]
        return ui.tags.ol(*rows, *extra, class_="slots")

    @render.ui
    def insurance():
        if sample_case():
            sc = service.load_scenario(sample_case())
            plan = sc["coverage"]["class"][0].get("name") or sc["coverage"]["class"][0]["value"]
            return ui.p(ui.tags.b("Insurance "), f"{plan}, from the sample patient's card", class_="ins-note")
        return ui.div(
            ui.input_select("plan", "Insurance plan", _plans(), width="100%"),
            ui.input_text("zip", "Home ZIP", value="78745", width="100%"),
            class_="ins-row",
        )

    def _request(human_confirmed: bool = False) -> dict:
        opts = {"llm": bool(input.llm()), "human_confirmed": human_confirmed}
        if input.model_id() and input.model_id() != aws.BEDROCK_MODEL_ID:
            opts["model_id"] = input.model_id()
        intake = input.intake().strip() or None
        if sample_case():
            req_ = {"scenario": sample_case(), "options": opts}
            if intake and intake != _sample_intake_text(sample_case()):
                req_["inputs"] = {"intake": intake}
            return req_
        plan_id = input.plan()
        return {
            "inputs": {
                "documents": [raw for _, raw, _ in docs()],
                "intake": intake,
                "coverage": {"resourceType": "Coverage", "status": "active",
                             "class": [{"type": {"text": "plan"}, "value": plan_id, "name": _plans()[plan_id]}]},
                "patient": {"address": [{"postalCode": (input.zip() or "78745").strip()}]},
            },
            "options": opts,
        }

    # -- run
    @ui.bind_task_button(button_id="run")
    @reactive.extended_task
    async def run_task(request: dict, demo_fill: bool) -> dict:
        return await asyncio.to_thread(pipeline.run, request, inbox.put, demo_fill)

    def _start(request: dict) -> None:
        events.set([])
        confirmed.set(False)
        started.set(time.time())
        last_request.set(request)
        run_task(request, bool(input.demo()))

    @reactive.effect
    @reactive.event(input.run)
    def _run():
        if not docs():
            ui.notification_show("Add your PDFs or load a sample patient first.", type="warning")
            return
        _start(_request())

    @reactive.effect
    @reactive.event(input.clinician_ok)
    def _rerun_confirmed():
        if last_request():
            r = {**last_request(), "options": {**last_request()["options"], "human_confirmed": True}}
            _start(r)

    @reactive.effect
    def _drain():
        if run_task.status() == "running":
            reactive.invalidate_later(0.2)
        new = []
        while not inbox.empty():
            new.append(inbox.get_nowait())
        if new:
            with reactive.isolate():
                events.set(events() + new)

    # -- outputs
    @render.ui
    def clock():
        if run_task.status() == "running":
            reactive.invalidate_later(1)
            return ui.span(f"Working · {time.time() - started():.0f} s", class_="clock live")
        if run_task.status() == "success":
            return ui.span(f"Done in {run_task.result()['elapsed_seconds']:.0f} s", class_="clock")
        return None

    @render.ui
    def course():
        return ui.HTML(views.course_map(views.agent_states(events()), events()))

    @render.ui
    def log():
        return ui.div(ui.h3("Handoffs"), ui.HTML(views.handoff_log(events())), class_="log")

    @render.ui
    def tasks():
        if run_task.status() == "running":
            reactive.invalidate_later(1)
        return ui.HTML(views.task_table(views.agent_states(events()), now=time.time()))

    @render.ui
    def results():
        if run_task.status() == "error":
            return ui.p(f"The run failed: {run_task.error()}", class_="error")
        if run_task.status() == "running":
            return ui.p("The care team is reading your reports. Follow their handoffs above.", class_="empty")
        if run_task.status() != "success":
            return ui.p("Add your PDFs or load a sample patient, then select Share with CareRelay.", class_="empty")
        report = run_task.result()
        button = ""
        if views.next_steps_view(report["stages"].get("next_steps", {})).appointments and report["stages"]["next_steps"].get("status") == "ok":
            button = str(ui.input_action_button("undo", "Undo confirmation", class_="btn-quiet") if confirmed()
                         else ui.input_action_button("confirm", "Confirm appointments", class_="btn-course"))
        gate = str(ui.input_action_button("clinician_ok", "A clinician has reviewed it: plan follow-ups", class_="btn-course"))
        return ui.HTML(views.results(report, confirmed(), button, gate))

    @render.ui
    def downloads():
        req(run_task.status() == "success")
        return ui.div(ui.download_button("dl_md", "Download report (Markdown)", class_="btn-quiet"),
                      ui.download_button("dl_json", "Download report (JSON)", class_="btn-quiet"), class_="downloads")

    @render.download(filename="carerelay_report.md")
    def dl_md():
        yield run_task.result()["report"]["markdown"]

    @render.download(filename="carerelay_report.json")
    def dl_json():
        yield json.dumps(run_task.result(), indent=1, default=str)

    @reactive.effect
    @reactive.event(input.confirm)
    def _confirm():
        confirmed.set(True)

    @reactive.effect
    @reactive.event(input.undo)
    def _undo():
        confirmed.set(False)


def _sample_intake_text(case_id: str) -> str:
    intake = service.load_scenario(case_id).get("intake") or {}
    lines = []
    if intake.get("medications"):
        lines.append("Medications: " + ", ".join(intake["medications"]))
    if intake.get("history"):
        lines.append("Conditions: " + "; ".join(intake["history"]))
    return "\n".join(lines)


app = App(app_ui, server, static_assets=WWW)
