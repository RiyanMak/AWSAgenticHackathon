"""CareRelay patient UI (Shiny for Python, Course theme).

    shiny run src/carerelay/ui/app.py        # from the repo root, after: pip install -e ".[ui]"

Runs service.handle() in a worker thread and draws its progress as an agent course: each agent is a
control on the purple route, the handoff log lists what each agent passed on, and the result
panel shows the ledger, proposed appointments and while-you-wait options. See docs/FRONTEND.md.
"""

from __future__ import annotations

import asyncio
import os
import queue
from pathlib import Path

from shiny import App, reactive, render, ui

from carerelay import service
from carerelay.ui import pipeline, views

WWW = Path(__file__).parent / "www"


def _scenarios() -> dict[str, str]:
    return {s["case_id"]: f"{s['case_id']} · {s['exam']}" for s in service.list_scenarios()}


app_ui = ui.page_fillable(
    ui.head_content(
        ui.tags.link(rel="stylesheet", href="tokens.css"),
        ui.tags.link(rel="stylesheet", href="course.css"),
        ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
    ),
    ui.tags.header(ui.div("CareRelay", class_="brand"), ui.span("Synthetic data · prototype · not medical advice", class_="synth"), class_="top"),
    ui.div(
        ui.tags.aside(
            ui.h2("Your reports"),
            ui.input_radio_buttons("mode", None, {"scenario": "Sample patient", "upload": "Upload my files"}, inline=True),
            ui.panel_conditional(
                "input.mode === 'scenario'",
                ui.input_select("scenario", "Sample patient", _scenarios()),
            ),
            ui.panel_conditional(
                "input.mode === 'upload'",
                ui.input_file("labs_pdf", "Lab results (PDF)", accept=[".pdf"]),
                ui.input_file("radiology_pdf", "Imaging report (PDF)", accept=[".pdf"]),
                ui.input_file("history_pdf", "Health summary (PDF)", accept=[".pdf"]),
            ),
            ui.input_switch("llm", "Use Bedrock for summaries", value=os.environ.get("CARERELAY_LLM", "0") == "1"),
            ui.input_switch("demo", "Fill agents not built yet with demo data", value=True),
            ui.input_task_button("run", "Read my reports", label_busy="Agents working..."),
            class_="inputs",
        ),
        ui.tags.main(
            ui.tags.section(
                ui.h2("Agent course"),
                ui.div(ui.output_ui("course"), ui.output_ui("log"), class_="course-row"),
                ui.output_ui("tasks"),
                class_="panel",
            ),
            ui.tags.section(ui.output_ui("results"), class_="panel results"),
            ui.tags.footer(service.DISCLAIMER),
        ),
        class_="layout",
    ),
    padding=0,
    gap=0,
    title="CareRelay",
)


def server(input, output, session):
    events: reactive.Value[list] = reactive.Value([])
    confirmed = reactive.Value(False)
    inbox: queue.Queue = queue.Queue()

    def _request() -> dict:
        req: dict = {"options": {"llm": bool(input.llm())}}
        if input.mode() == "scenario":
            req["scenario"] = input.scenario()
        else:
            req["inputs"] = {k: (input[k]()[0]["datapath"] if input[k]() else None) for k in ("labs_pdf", "radiology_pdf", "history_pdf")}
        return req

    @ui.bind_task_button(button_id="run")
    @reactive.extended_task
    async def run_task(req: dict, demo_fill: bool) -> dict:
        return await asyncio.to_thread(pipeline.run, req, inbox.put, demo_fill)

    @reactive.effect
    @reactive.event(input.run)
    def _start():
        events.set([])
        confirmed.set(False)
        run_task(_request(), bool(input.demo()))

    @reactive.effect
    def _drain():
        # Pull agent events from the worker thread while the run is in flight
        if run_task.status() == "running":
            reactive.invalidate_later(0.2)
        new = []
        while not inbox.empty():
            new.append(inbox.get_nowait())
        if new:
            with reactive.isolate():
                events.set(events() + new)

    @render.ui
    def course():
        return ui.HTML(views.course_map(views.agent_states(events()), events()))

    @render.ui
    def log():
        return ui.div(ui.h3("Handoffs"), ui.HTML(views.handoff_log(events())), class_="log")

    @render.ui
    def tasks():
        return ui.HTML(views.task_table(views.agent_states(events())))

    @render.ui
    def results():
        if run_task.status() == "error":
            return ui.p(f"The run failed: {run_task.error()}", class_="error")
        if run_task.status() == "running":
            return ui.p("The agents are reading your reports. Follow their handoffs above.", class_="empty")
        if run_task.status() != "success":
            return ui.p("Pick a sample patient or upload your reports, then select Read my reports.", class_="empty")
        report = run_task.result()
        button = ""
        if report["stages"].get("next_steps", {}).get("appointments"):
            button = str(ui.input_action_button("undo", "Undo confirmation", class_="btn-quiet") if confirmed()
                         else ui.input_action_button("confirm", "Confirm appointments", class_="btn-course"))
        return ui.HTML(views.results(report, confirmed(), button))

    @reactive.effect
    @reactive.event(input.confirm)
    def _confirm():
        confirmed.set(True)

    @reactive.effect
    @reactive.event(input.undo)
    def _undo():
        confirmed.set(False)


app = App(app_ui, server, static_assets=WWW)
