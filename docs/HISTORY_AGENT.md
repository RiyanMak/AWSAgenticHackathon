# History Agent

Turns a patient's medical history into a coded `HistoryProfile` that Summarize, Wellness and Next Steps consume. Code lives in `src/carerelay/history/`. Back to [README](../README.md).

Design rule: **parsing is deterministic, the model only narrates.** Conditions, medications, allergies, procedures and risk flags come from parsers and lookup tables. The LLM writes the 2 to 3 sentence summary and up to five clinician notes, and nothing it says changes the structured fields.

## Inputs

| Input | Parser | Coding | Notes |
|---|---|---|---|
| FHIR R4 bundle (Synthea, Synthea Coherent) | `parsers/fhir.py` | SNOMED, RxNorm from the bundle | Resolves `medicationReference` to `Medication` resources, de-duplicates repeat prescriptions, derives specialties from encounter and care-team text |
| MIMIC-IV hosp tables for one `subject_id` | `parsers/mimic.py` | ICD-9/10 via `d_icd_*` lookups | `.csv` or `.csv.gz`. Medications from the latest admission are marked active. No allergy table, so pair with an intake form |
| Free-text intake form | `parsers/intake.py` | ICD-10-CM and RxNorm via Comprehend Medical | Sections `Conditions:`, `Medications:`, `Allergies:`, `Surgeries:`, `Doctors:`. Falls back to uncoded text with a warning when Comprehend Medical is unavailable or `offline=True` |

Any combination can be merged in one call (for example MIMIC rows plus an intake form for allergies).

## Output: `HistoryProfile`

```text
patient            id, gender, birth_date, age_years
conditions         CodedItem[]  display, code, system, status, onset, detail, confidence, source_ref
medications        CodedItem[]  status active|stopped, dose text in detail
allergies          CodedItem[]  reaction and criticality in detail
procedures         CodedItem[]
care_team          provider display names seen in the history
known_specialists  lower-case specialties the patient already sees (cardiology, nephrology, ...)
risk_flags         ckd, diabetes, hypertension, liver, pregnancy, anticoagulant, heart_failure, ...
source             fhir | csv | intake_text | degraded
warnings           parse problems; non-empty means review
summary            LLM-written, plain language
clinician_notes    LLM-written, up to 5 items
```

`source == "degraded"` means the input could not be parsed. Summarize then treats every abnormal finding as incidental, which is the conservative direction, and the LLM is not called.

## Risk flags and the expected-vs-incidental table

`risk_flags.py` holds small prefix tables for ICD-10-CM, ICD-9-CM and the SNOMED codes Synthea emits, plus display-text and medication-name keyword fallbacks. Only **active** conditions and medications contribute flags, so a resolved pregnancy or a stopped anticoagulant does not.

`EXPLAINS` maps each flag to the lab analytes and imaging labels it can explain. `explained_by("Glucose", profile)` returns `["diabetes"]` for a diabetic patient and `[]` otherwise. Summarize uses this to set `Finding.explained_by` or put the finding in the incidental ledger. `nsaid_excluded(profile)` is the Wellness hard filter from [SAFETY.md](SAFETY.md) rules 2 and 3.

All three tables are a labeled prototype rule set, not a clinical standard.

## Running it

```bash
cd AgenticAIHackathonAWS
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q                      # 20 tests, offline

# parse only (no AWS calls)
.venv/bin/python -m carerelay.history --fhir data/samples/history/synthea_coherent_sample_bundle.json --no-llm
.venv/bin/python -m carerelay.history --mimic-dir data/samples/history/mimic_demo_subject_10004235 --subject 10004235 \
    --intake "Allergies: sulfa (hives)" --offline --no-llm

# full run: deterministic parse, then Bedrock writes summary and clinician notes
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0   # pick from the workshop allowlist
.venv/bin/python -m carerelay.history --fhir data/samples/history/synthea_coherent_sample_bundle.json --out profile.json
```

From Python:

```python
from carerelay.history import build_history_profile, run_history_agent, make_history_agent

profile = build_history_profile(fhir_bundle="bundle.json")                 # no LLM
profile = run_history_agent(fhir_bundle="bundle.json", intake_text=text)   # with summary
agent = make_history_agent()                                               # Strands Agent for the graph
```

`make_history_agent()` returns a Strands `Agent` named `history` whose tools are `parse_fhir_history`, `parse_mimic_history`, `parse_intake_history`, `derive_risk_flags` and `check_finding_explained`. In the CareRelay graph it is the third parallel entry node next to Lab and Radiology (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## AWS permissions and failure handling

| Call | Permission | On failure |
|---|---|---|
| Bedrock Converse (summary) | `bedrock:InvokeModel*` on the inference profile | Profile returned without summary, `warnings` gets `LLM summary unavailable: <error>` |
| Comprehend Medical `InferICD10CM`, `InferRxNorm` | `comprehendmedical:InferICD10CM`, `comprehendmedical:InferRxNorm` | Items kept as uncoded text, keyword flags still apply, warning recorded |

Both failure paths were exercised on 2026-10-23: a model the account could not access, and an IAM user without Comprehend Medical rights. Neither crashed the pipeline, which is guardrail 2 in [SAFETY.md](SAFETY.md).

## Known limits

- Synthea Coherent patients were generated in 2022, so `age_years` computed today can be implausible. Pass `as_of` to `parse_fhir_bundle` for a fixed reference date.
- MIMIC "active" medications are the orders from the latest admission, not a verified discharge list.
- Specialty detection is keyword based. Synthea encounters rarely carry specialties, so `known_specialists` is often short for FHIR input and richer for the intake form.
- The intake parser never sends the allergies section to Comprehend Medical; allergies stay as written.
