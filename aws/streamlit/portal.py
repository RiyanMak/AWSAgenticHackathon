"""Patient-portal demo: drag the portal PDFs in, watch the care team work, read the result.

    streamlit run aws/streamlit/portal.py --server.port 8501

Uploads are sorted by content (history / labs / radiology) so the patient never labels files.
Stages light up as each agent finishes (service.iter_stages). Synthetic data only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from carerelay import service

STAGE_LABELS = {
    "history": ("🗂️", "Medical history"),
    "lab": ("🧪", "Lab results"),
    "radiology": ("🩻", "Imaging report"),
    "summarize": ("🧭", "Care summary"),
    "wellness": ("🥗", "While you wait"),
    "next_steps": ("📅", "Next steps"),
}
STATUS_TEXT = {
    "pending": ("⏳", "waiting"),
    "running": ("🔄", "working"),
    "ok": ("✅", "done"),
    "skipped": ("➖", "not provided"),
    "needs_clinical_reevaluation": ("⚠️", "needs clinician"),
    "not_implemented": ("🚧", "coming soon"),
}
KIND_LABEL = {"history": "Health summary", "labs": "Lab report", "radiology": "Imaging report", "unknown": "Not recognised"}

st.set_page_config(page_title="MyHealth Portal · CareRelay", page_icon="🩺", layout="wide")
st.markdown(
    """
    <style>
      .portal-head {background:#1d4e89;color:white;padding:14px 22px;border-radius:10px;margin-bottom:12px}
      .portal-head h2 {margin:0;font-size:1.4rem;color:white}
      .portal-head p {margin:4px 0 0;opacity:.85}
      .disclaimer {font-size:.8rem;color:#616e7c;border-top:1px solid #cbd2d9;padding-top:8px;margin-top:18px}
      [data-testid="stFileUploaderDropzone"] {border:2px dashed #1d4e89;background:#f4f7fb;padding:22px}
    </style>
    <div class="portal-head"><h2>MyHealth Portal</h2>
    <p>Records &rsaquo; Share with CareRelay &nbsp;·&nbsp; SYNTHETIC TEST ENVIRONMENT, fictional patients only</p></div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Run options")
    use_llm = st.toggle("Use Bedrock for narration and coding", value=os.environ.get("CARERELAY_USE_AWS") == "1")
    model_id = st.text_input("Bedrock model id (blank = default)", value=os.environ.get("BEDROCK_MODEL_ID", ""))
    st.divider()
    st.caption("No files handy? Load a bundled synthetic patient as if they had been dropped in.")
    scenarios = service.list_scenarios()
    sample = st.selectbox("Sample patient", ["(none)"] + [s["case_id"] for s in scenarios])
    if st.button("Load sample records") and sample != "(none)":
        sc = service.load_scenario(sample)
        st.session_state["dropped"] = [
            (Path(sc[k]).name, Path(sc[k]).read_bytes()) for k in ("history_pdf", "labs_pdf", "radiology_pdf")
        ]
        st.session_state["intake"] = sc["intake"]
        st.session_state.pop("report", None)

left, right = st.columns([5, 4])

with left:
    st.subheader("1. Drop your records")
    st.write("Drag the PDFs you downloaded from your clinic, lab and imaging portals. We sort them for you.")
    uploads = st.file_uploader("Drop PDFs here", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
    if uploads:
        st.session_state["dropped"] = [(u.name, u.getvalue()) for u in uploads]
        st.session_state.pop("intake", None)

    dropped: list[tuple[str, bytes]] = st.session_state.get("dropped", [])
    if dropped:
        st.markdown("**Detected documents**")
        for name, raw in dropped:
            kind = service.classify_pdf(raw)
            icon = "✅" if kind != "unknown" else "❓"
            st.write(f"{icon} `{name}` → {KIND_LABEL[kind]}")
    intake_default = st.session_state.get("intake")
    intake_text = st.text_area(
        "Anything else we should know? (current medicines, allergies, conditions)",
        value=("Medications: " + ", ".join(intake_default.get("medications", []))) if isinstance(intake_default, dict) else "",
        height=90,
    )
    run = st.button("2. Share with CareRelay", type="primary", disabled=not dropped, width="stretch")

with right:
    st.subheader("Care team progress")
    tiles = {name: st.empty() for name in service.STAGES}

    def paint(statuses: dict[str, str]) -> None:
        for name, ph in tiles.items():
            icon, label = STAGE_LABELS[name]
            s_icon, s_text = STATUS_TEXT.get(statuses.get(name, "pending"), ("⏳", statuses.get(name, "")))
            ph.markdown(f"{icon} **{label}** &nbsp; {s_icon} _{s_text}_")

    paint({})

if run:
    request = {
        "inputs": {"documents": [raw for _, raw in dropped], "intake": intake_text or None},
        "options": {"llm": use_llm, **({"model_id": model_id} if model_id else {})},
    }
    statuses = {n: "pending" for n in service.STAGES}
    report = None
    try:
        for event in service.iter_stages(request):
            if event["event"] == "inputs":
                for name, present in event["present"].items():
                    statuses[name] = "running" if present else "skipped"
                for w in event["warnings"]:
                    st.warning(w)
            elif event["event"] == "stage":
                statuses[event["name"]] = event["result"]["status"]
            elif event["event"] == "report":
                report = event["report"]
            paint(statuses)
    except service.ServiceError as exc:
        st.error(str(exc))
    if report:
        st.session_state["report"] = report

report = st.session_state.get("report")
if report:
    st.divider()
    st.subheader("3. What your records say")
    tab_plain, tab_findings, tab_json = st.tabs(["In plain language", "Findings and evidence", "Structured (JSON)"])
    with tab_plain:
        st.markdown(report["report"]["markdown"])
    with tab_findings:
        for name in ("lab", "radiology"):
            stage = report["stages"].get(name, {})
            if stage.get("status") != "ok":
                continue
            st.markdown(f"**{STAGE_LABELS[name][1]}**")
            rows = [
                {"severity": f["severity"], "finding": f["label"], "value": f.get("value") or "", "evidence": f["evidence"],
                 "confidence": f["confidence"], "specialty": f.get("specialty_hint") or ""}
                for f in stage["result"].get("findings", [])
            ]
            st.dataframe(rows, width="stretch") if rows else st.caption("Nothing outside the reference range.")
        hist = report["stages"].get("history", {})
        if hist.get("status") == "ok":
            p = hist["profile"]
            st.markdown("**Medical history**")
            st.write({"risk_flags": p["risk_flags"], "known_specialists": p["known_specialists"],
                      "allergies": [a["display"] for a in p["allergies"]], "warnings": p["warnings"]})
    with tab_json:
        st.json(report["stages"])
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download report (Markdown)", report["report"]["markdown"], file_name="carerelay_report.md")
    c2.download_button("Download report (JSON)", json.dumps(report, indent=1), file_name="carerelay_report.json")
    c3.caption(f"Elapsed {report['elapsed_seconds']} s")

st.divider()
with st.expander("How this runs on AWS", expanded=False):
    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    a, b = st.columns(2)
    with a:
        st.markdown("**Deployment lanes**")
        if (docs_dir / "aws_architecture_1.png").exists():
            st.image(str(docs_dir / "aws_architecture_1.png"), width="stretch")
        st.markdown(
            "- **Amazon Bedrock** (Claude): reads the lab and imaging PDFs, codes free-text history, writes the plain-language narration. Rules decide every flag and dose.\n"
            "- **Amazon Comprehend Medical**: ICD-10-CM and RxNorm coding of patient-typed history, with Bedrock as fallback.\n"
            "- **Bedrock AgentCore Runtime**: hosts this same pipeline as an arm64 container (`POST /invocations`).\n"
            "- **AWS Lambda + Function URL**: shareable API; reports saved to a private **S3** bucket with presigned links, 14-day expiry.\n"
            "- **CloudWatch Logs**, **IAM** least-privilege roles, **ECR** for both images. This page is the Streamlit lane, running the team in-process."
        )
    with b:
        st.markdown("**The care team**")
        if (docs_dir / "agent_architecture_1.png").exists():
            st.image(str(docs_dir / "agent_architecture_1.png"), width="stretch")
        st.markdown(
            "History, Lab and Radiology run in parallel on the uploaded PDFs. Summarize merges them and keeps the incidental-findings ledger; "
            "Wellness and Next Steps (Insurance + Scheduling) fan out from it. Deterministic tools do the math; humans confirm every appointment. "
            "Details: `docs/AWS_INFRASTRUCTURE.md`."
        )

st.markdown(f'<div class="disclaimer">{service.DISCLAIMER}</div>', unsafe_allow_html=True)
