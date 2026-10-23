"""Lane C: live demo UI. Runs the pipeline in-process on SageMaker Studio, EC2 or a laptop.

    streamlit run aws/streamlit/app.py --server.port 8501
"""

from __future__ import annotations

import json
import os

import streamlit as st

from carerelay import service

st.set_page_config(page_title="CareRelay", page_icon="🩺", layout="wide")
st.title("CareRelay")
st.caption("Hackathon prototype on synthetic data. Not a clinical system or medical advice.")

with st.sidebar:
    st.header("Input")
    mode = st.radio("Source", ["Bundled scenario", "Upload files"])
    use_llm = st.toggle("Use Bedrock for coding and summaries", value=True)
    model_id = st.text_input("Bedrock model id (blank = default)", value=os.environ.get("BEDROCK_MODEL_ID", ""))
    region = st.text_input("AWS region (blank = default)", value=os.environ.get("AWS_REGION", ""))

request: dict = {"options": {"llm": use_llm}}
if model_id:
    request["options"]["model_id"] = model_id
if region:
    request["options"]["region"] = region

if mode == "Bundled scenario":
    scenarios = service.list_scenarios()
    labels = {f"{s['case_id']}  |  {s['exam']}  |  {s['plan']}": s["case_id"] for s in scenarios}
    choice = st.selectbox("Scenario", list(labels))
    request["scenario"] = labels[choice]
else:
    history = st.file_uploader("Medical history PDF", type=["pdf"])
    labs = st.file_uploader("Lab results PDF", type=["pdf"])
    radiology = st.file_uploader("Radiology report PDF", type=["pdf"])
    intake = st.text_area("Intake answers (Conditions:, Medications:, Allergies:)", height=120)
    request["inputs"] = {
        "history_pdf": history.getvalue() if history else None,
        "labs_pdf": labs.getvalue() if labs else None,
        "radiology_pdf": radiology.getvalue() if radiology else None,
        "intake": intake or None,
    }

if st.button("Run CareRelay", type="primary"):
    with st.spinner("Running agents..."):
        try:
            report = service.handle(request)
        except service.ServiceError as exc:
            st.error(str(exc))
            st.stop()
    cols = st.columns(len(service.STAGES))
    for col, name in zip(cols, service.STAGES):
        status = report["stages"][name]["status"]
        col.metric(name.replace("_", " ").title(), status)
    st.markdown(report["report"]["markdown"])
    with st.expander("Structured output (JSON)"):
        st.json(report["stages"])
    st.download_button("Download report (Markdown)", report["report"]["markdown"], file_name="carerelay_report.md")
    st.download_button("Download report (JSON)", json.dumps(report, indent=1), file_name="carerelay_report.json")
    st.caption(f"Elapsed {report['elapsed_seconds']} s")
