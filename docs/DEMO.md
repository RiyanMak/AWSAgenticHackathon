# Demo runbook

Show the patient's experience: drag the portal PDFs in, watch the care team work, read the result. Back to [README](../README.md).

## The flow on screen

1. **Drop.** Run `./run.sh` and open the Shiny portal (`src/carerelay/ui/app.py`, port 8501). Drag the three PDFs from `data/output/case_001/` onto the drop zone: the three numbered slots (Health summary, Lab results, Imaging report) fill in by content; nothing is labelled by hand. For uploads, pick the insurance plan and ZIP. Or choose a sample patient and select **Load sample records** (insurance comes from the sample's card). The header shows whether Amazon Bedrock is connected.
2. **Share.** Select **Share with CareRelay**. The agent course fills in live: Lab, Radiology and History start together, each control ticks when its agent is done, the leg flows while a handoff is in flight, and the handoff log lists what each agent passed on, including each Next Steps to Insurance check. A clock shows elapsed time (about 80-110 s on Bedrock for case_001).
3. **Read.** A plain-language headline, the findings with owners and a "Where your report says this" quote, the proposed in-network appointments with cost, caregiver notes, and while-you-wait options with ruled-out items. If an urgent result needs a clinician first, a red gate appears with a button to continue once reviewed. Download buttons give the judges a Markdown or JSON report.

The older Streamlit portal (`./run.sh portal`) still works as a fallback.

## Setup, 30 minutes before

```bash
cd AgenticAIHackathonAWS
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q tests data/tests                      # must be green
export AWS_REGION=us-east-1 CARERELAY_USE_AWS=1 BEDROCK_MODEL_ID=<allow-listed profile>
aws bedrock-runtime converse --region $AWS_REGION --model-id $BEDROCK_MODEL_ID \
  --messages '[{"role":"user","content":[{"text":"Reply OK"}]}]'           # model access check
./run.sh                                                             # Shiny portal on :8501
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
2. The portal misbehaves: `./run.sh portal` for the older page, or play the recording and narrate the same three beats.
3. Nothing works: open the JSON report saved from the warm-up run.

## Numbers you can quote

- 212 of 212 lab rows read exactly across the 10 cases (offline parser).
- History codes exact on all 10 cases; questionnaire coding by Bedrock verified on case_004 and case_006.
- Radiology incidental recall: quote the Bedrock run from `python -m carerelay.eval --aws` once recorded; the offline fallback alone is 8 of 23.

Do not claim clinical validation. Synthetic data only, not medical advice, humans confirm every appointment.
