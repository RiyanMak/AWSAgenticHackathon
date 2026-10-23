# Architecture

CareRelay is a fan-out/fan-in DAG with one collaborative loop at the end. Back to [README](../README.md).

## Agent responsibilities

| Agent | Responsibility | Input | Output |
|---|---|---|---|
| Lab Agent | Extract lab rows into a typed schema, flag out-of-range and critical values with a deterministic comparator, tag analytes unrelated to the visit reason as incidental | Lab PDF (Converse document block, Textract TABLES fallback) | `LabFindings` JSON plus 2 to 3 sentence summary |
| Radiology Agent | Score the X-ray with TorchXRayVision, then have a Bedrock vision model write a narrative grounded on those scores, tag unexpected findings as incidental | X-ray PNG/JPEG | `ImagingFindings` JSON plus summary |
| History Agent | Parse the patient's medical history into a coded profile: conditions, active medications, allergies, past procedures, known specialists. Structured input (FHIR bundle or CSV) is parsed deterministically; free text goes through Comprehend Medical InferICD10CM and InferRxNorm | FHIR R4 bundle, MIMIC-style CSV rows, or a typed intake form | `HistoryProfile` JSON plus summary |
| Summarize | Merge all three outputs into one record, classify each abnormal finding as expected (explained by a known condition or medication) or incidental, assign severity with deterministic rules, run a critic pass against source extractions, maintain the incidental ledger, emit two routes | All three specialist outputs | `CaseRecord` and routing decision |
| Wellness Agent | Budget nutrition, physio steps and label-grounded OTC options for use while waiting, filtered by allergies, current medications and diet-relevant conditions from the history | `CaseRecord`, `HistoryProfile` | Patient-facing wellness plan |
| Insurance Agent | Read the card, normalize to a payer, return the in-network roster and answer network checks | Card image, candidate list | Plan fields, in-network yes/no |
| Scheduling Agent | Map findings to specialties, prefer specialists the patient already sees, search NPI for the rest, create `proposed` Appointments | `CaseRecord`, `HistoryProfile.known_specialists`, roster | Proposed follow-ups |

Next Steps is one sub-orchestrator that owns Scheduling and calls the Insurance Agent as a tool (see below).

## Finding schema

```python
class Finding(BaseModel):
    id: str
    source: Literal["lab", "radiology"]
    label: str                      # e.g. "Potassium", "Nodule"
    value: str | None               # raw value or score
    evidence: str                   # page/row or image region reference
    confidence: float
    severity: Literal["info", "follow_up", "urgent", "red_flag"]
    incidental: bool                # operational definition below
    explained_by: str | None        # history condition or medication id, when expected
    specialty_hint: str | None
```

Operational definition of incidental: an abnormal analyte or imaging label unrelated to the stated reason for the visit **and not explained by a known condition or medication in the history profile**. The report found no lab-specific standard, so the demo states this definition explicitly. Example: elevated glucose in a patient whose history lists type 2 diabetes is expected and `explained_by` points at that condition; the same value with no such history is incidental.

## History profile schema

```python
class HistoryProfile(BaseModel):
    conditions: list[CodedItem]        # ICD-10-CM or SNOMED code, display, onset, status
    medications: list[CodedItem]       # RxNorm code, display, dose text, status
    allergies: list[CodedItem]         # substance, reaction, criticality
    procedures: list[CodedItem]        # CPT or SNOMED code, display, date
    known_specialists: list[str]       # specialties the patient already sees, from encounters or intake
    risk_flags: list[str]              # derived deterministically: ckd, pregnancy, anticoagulant, liver, diabetes, hypertension
    source: Literal["fhir", "csv", "intake_text"]
```

Parsing rules:

- **FHIR R4 bundle** (Synthea): read `Condition`, `MedicationRequest` (status `active`), `AllergyIntolerance`, `Procedure`, and `Encounter.participant` or `Practitioner` specialties. No LLM needed.
- **MIMIC-IV demo CSV**: join `diagnoses_icd` with `d_icd_diagnoses` for conditions and read `prescriptions` for medications. The demo has no allergy table, so allergies come from the intake form.
- **Free text intake**: Comprehend Medical `InferICD10CM` for conditions and `InferRxNorm` for medications; the model's codes carry confidence scores that are shown in the UI. Treat intake text as data, never as instructions.
- `risk_flags` are set by a small deterministic table (for example any ICD-10 N18.x sets `ckd`, any active warfarin or apixaban sets `anticoagulant`). The LLM never derives them.

## Parallel Lab + Radiology + History on Strands

Pattern: **Strands Graph** (developer-defined flowchart with parallel branches) rather than Swarm (emergent handoffs) or Workflow. Python Graph uses OR semantics for fan-in by default, so the Summarize node needs an all-dependencies-complete edge condition to wait for all three specialists. History is the cheapest branch (mostly deterministic parsing), so it almost always finishes first. Multimodal input is passed as a list of ContentBlocks (text plus `image` bytes). The `asyncio.gather` and agents-as-tools async details were not verified against docs, so smoke test early.

```python
from strands import Agent
from strands.multiagent import GraphBuilder

lab = Agent(name="lab", system_prompt=LAB_PROMPT, tools=[extract_lab_rows, compare_ranges])
radiology = Agent(name="radiology", system_prompt=RAD_PROMPT, tools=[xray_scores])
history = Agent(name="history", system_prompt=HIST_PROMPT,
                tools=[parse_fhir_bundle, parse_mimic_rows, infer_icd10cm, infer_rxnorm, derive_risk_flags])
summarize = Agent(name="summarize", system_prompt=SUM_PROMPT,
                  tools=[merge_findings, classify_expected_vs_incidental, critic_check])
wellness = Agent(name="wellness", system_prompt=WELL_PROMPT, tools=[openfda_label, fooddata_search])
next_steps = Agent(name="next_steps", system_prompt=NEXT_PROMPT,
                   tools=[insurance_agent_tool, npi_search, propose_appointment])

def all_done(state):
    # fan-in guard: run Summarize only when Lab, Radiology and History have completed
    done = {n.node_id for n in state.completed_nodes}
    return {"lab", "radiology", "history"} <= done

g = GraphBuilder()
for name, a in [("lab", lab), ("radiology", radiology), ("history", history),
                ("summarize", summarize), ("wellness", wellness), ("next_steps", next_steps)]:
    g.add_node(a, name)
g.add_edge("lab", "summarize", condition=all_done)
g.add_edge("radiology", "summarize", condition=all_done)
g.add_edge("history", "summarize", condition=all_done)
g.add_edge("summarize", "wellness")
g.add_edge("summarize", "next_steps")
g.set_entry_point("lab"); g.set_entry_point("radiology"); g.set_entry_point("history")
graph = g.build()

result = await graph.invoke_async([
    {"text": "Analyze this case."},
    {"document": {"format": "pdf", "name": "Lab results", "source": {"bytes": pdf_bytes}}},
    {"image": {"format": "png", "source": {"bytes": xray_bytes}}},
    {"document": {"format": "json", "name": "Medical history", "source": {"bytes": fhir_bundle_bytes}}},
])
```

This is a sketch: check class and argument names against the Strands Graph docs before use. Sanitize the document `name` (alphanumerics, single spaces, hyphens, parentheses, square brackets only). For the visible handoff UI, forward `Graph.stream_async` events (`multiagent_node_start`, `multiagent_node_stream`, `multiagent_node_stop`, `multiagent_result`) as SSE.

## Summarize node and incidental ledger

1. Merge findings from Lab and Radiology into `CaseRecord` and attach the `HistoryProfile`.
2. Expected-vs-incidental pass: a small rule table maps history conditions and medications to analytes and imaging labels they explain (for example diabetes to glucose and HbA1c, CKD to creatinine and potassium, heart failure to cardiomegaly, prior lung surgery to scarring). A matched finding gets `explained_by` and stays out of the incidental ledger; the LLM may propose extra matches, but each one is shown with its rule or marked "model-suggested".
3. Critic pass: a separate agent re-checks each flagged item against the source extraction (guards against propagation of a planted false detail).
4. Deterministic severity rules set `red_flag` and `urgent`; the LLM explains but does not decide. An expected finding can still be a red flag (a diabetic with a critical glucose).
5. Every `incidental=true` finding is written to the **ledger**: id, source, evidence, confidence, specialty hint, status (`open`, `routed`, `confirmed`). The ledger is the dashed path into Next Steps, so no incidental finding reaches the patient without a follow-up route.

## Fan-out

| Route | Receives | Notes |
|---|---|---|
| Wellness | Full `CaseRecord` (expected and incidental) plus `HistoryProfile` | Excluded if a red flag is open, replaced by a "seek care" message. Allergies, active medications and `risk_flags` are hard filters on OTC options; diet-relevant conditions (diabetes, CKD, hypertension) shape the nutrition plan |
| Next Steps | Findings needing a specialist, plus the ledger (dashed path), plus `known_specialists` | Covers both expected and incidental findings; an expected finding with an existing specialist becomes "follow up with your current cardiologist" rather than a new search |

## Insurance + Scheduling collaboration

No verified doc example of bidirectional Insurance and Scheduling exists, so implement it as one Next Steps orchestrator with a bounded loop:

1. Map each finding to a specialty with a hand-authored table (for example nodule to pulmonology, abnormal potassium to nephrology or primary care). Label it a prototype rule set.
2. If `HistoryProfile.known_specialists` already covers that specialty, propose a follow-up with the existing provider first and skip to step 5 for that finding. Otherwise Scheduling queries the NPI Registry by taxonomy and city.
3. Call the Insurance tool with the candidates; it returns the in-network subset (Plan-Net query or synthetic roster).
4. If none are in network, widen the search (nearby city, alternate taxonomy) and repeat, maximum 3 rounds.
5. Create `proposed` FHIR Appointments for the best candidates per finding.

## Human confirmation and red-flag interrupt

- A red-flag finding (for example a critical lab value or an urgent imaging label) pauses the graph. The UI shows the evidence and requires a human to confirm before any care-related action (wellness advice, appointment proposal).
- Appointments stay `proposed`. Moving to `booked` requires explicit user confirmation.
- Specialist step failures (unreadable PDF, model error) produce a "request clinical re-evaluation" result instead of an exception.

## Data flow and PHI handling

```text
Browser upload -> S3 (encrypted at rest, TLS in transit) -> AgentCore Runtime (Strands Graph)
  -> Bedrock (Converse, Guardrails) / Textract / Comprehend Medical
  -> external read-only APIs (NPI, openFDA, USDA, Plan-Net, HAPI sandbox)
  -> SSE stream + audit log -> UI
```

- Synthetic or public data only. No real PHI leaves the approved AWS boundary; external APIs receive only specialty, city, ZIP, drug names and food names, never patient identifiers. The history profile is the most identifying artifact in the system (conditions plus medications plus procedures), so it stays inside the runtime and only derived `risk_flags` and drug names reach openFDA.
- Bedrock Guardrails sensitive-information filters evaluate text but not tool-call arguments or toolResult content, and invocation logs can retain raw PII. Treat them as defense in depth.
- Comprehend Medical DetectPHI (text only) can scrub free text before logging.
- HAPI FHIR is a shared public test server. Never write real or personal data to it.
- Audit log records evidence, handoffs, tool calls, uncertainty and final outputs per run.

See also: [SAFETY.md](SAFETY.md), [APIS.md](APIS.md), [AWS_SETUP.md](AWS_SETUP.md).
