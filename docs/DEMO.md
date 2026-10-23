# Demo runbook

Show the patient's experience: drag the portal PDFs in, watch the care team work, read the result. Back to [README](../README.md).

## The flow on screen

1. **Drop.** Open the portal page (`aws/streamlit/portal.py`). Drag the three PDFs from `data/output/case_001/` onto the drop zone. The page sorts them by content and shows "Health summary", "Lab report", "Imaging report" with check marks. Nothing is labelled by hand. If dragging misbehaves, the sidebar's "Load sample records" button drops the same files programmatically.
2. **Share.** Click "Share with CareRelay". The six stage tiles flip from waiting to working to done as each agent finishes, in completion order, because the page consumes `service.iter_stages()` rather than waiting for one blocking call.
3. **Read.** Three tabs: the plain-language report, a findings table with severity, evidence quote and confidence per item, and the raw JSON. Download buttons give the judges a file.

## Setup, 30 minutes before

```bash
cd AgenticAIHackathonAWS
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q tests data/tests                      # must be green
export AWS_REGION=us-east-1 CARERELAY_USE_AWS=1 BEDROCK_MODEL_ID=<allow-listed profile>
aws bedrock-runtime converse --region $AWS_REGION --model-id $BEDROCK_MODEL_ID \
  --messages '[{"role":"user","content":[{"text":"Reply OK"}]}]'           # model access check
.venv/bin/python -m streamlit run aws/streamlit/portal.py --server.port 8501
```

Do one full Bedrock run of case_001 before the audience arrives so clients are warm and you know the timing. Keep the recorded run (`presentation/media/demo.mp4`) open in a second window.

## What to say at each beat (case_001, Linda, 58)

- **Drop:** "Linda downloaded three PDFs from three portals. She drops them here. We sort them; she never labels anything."
- **Working:** "History, labs and imaging are read in parallel. Rules decide every flag; the model only writes the words."
- **Result:** point at the 9 mm nodule and the coronary calcification that only appeared in the findings section of the report, the A1c that the history marks as already-known prediabetes, and the allergy to dextromethorphan that filters cough syrups. Then the proposed in-network appointment waiting for a human to confirm. Do not click confirm.

Then prove it is hosted on AWS in one line from a terminal:

```bash
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $ARN --payload '{"scenario":"case_005"}' out.json && head -c 600 out.json
```

## Fallbacks, in order

1. Bedrock slow or denied: turn off the "Use Bedrock" toggle and rerun. Parsing, flags and the ledger are deterministic, so the demo still works.
2. Streamlit misbehaves: play the recording and narrate the same three beats.
3. Nothing works: open the JSON report saved from the warm-up run.

## Numbers you can quote

- 212 of 212 lab rows read exactly across the 10 cases (offline parser).
- History codes exact on all 10 cases; questionnaire coding by Bedrock verified on case_004 and case_006.
- Radiology incidental recall: quote the Bedrock run from `python -m carerelay.eval --aws` once recorded; the offline fallback alone is 8 of 23.

Do not claim clinical validation. Synthetic data only, not medical advice, humans confirm every appointment.
