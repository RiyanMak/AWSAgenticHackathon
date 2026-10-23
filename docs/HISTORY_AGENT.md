# History Agent

Turns a patient's medical history into a coded `HistoryProfile` that Summarize, Wellness and Next Steps consume. Code lives in `src/carerelay/history/`. Back to [README](../README.md).

Design rule: **parsing is deterministic, the model only narrates.** Conditions, medications, allergies, procedures and risk flags come from parsers and lookup tables. The LLM writes the 2 to 3 sentence summary and up to five clinician notes, and nothing it says changes the structured fields.

## Inputs

| Input | Parser | Coding | Notes |
|---|---|---|---|
| History PDF from the bundled cases (`data/output/<case>/history.pdf`) | `parsers/pdf.py` | PCP summary: ICD-10 codes read from the document. Questionnaire: coding cascade below | Detects `PATIENT HEALTH SUMMARY` vs `PATIENT HEALTH QUESTIONNAIRE`. Tables are parsed from pypdf layout-mode text using each header's column positions; a row starts only when the first column and a non-wrapping key column (code, date, prescriber) both have text, so wrapped names and notes are rejoined. Questionnaires are split by question number |
| FHIR R4 bundle (Synthea, Synthea Coherent) | `parsers/fhir.py` | SNOMED, RxNorm from the bundle | Resolves `medicationReference` to `Medication` resources, de-duplicates repeat prescriptions, derives specialties from encounter and care-team text |
| MIMIC-IV hosp tables for one `subject_id` | `parsers/mimic.py` | ICD-9/10 via `d_icd_*` lookups | `.csv` or `.csv.gz`. Medications from the latest admission are marked active. No allergy table, so pair with an intake form |
| Free-text intake form | `parsers/intake.py` | ICD-10-CM and RxNorm via Comprehend Medical | Sections `Conditions:`, `Medications:`, `Allergies:`, `Surgeries:`, `Doctors:`. Falls back to uncoded text with a warning when Comprehend Medical is unavailable or `offline=True` |

Any combination can be merged in one call (for example a history PDF plus the intake answers, or MIMIC rows plus an intake form for allergies).

### Coding cascade for free text

`coding.py` codes free-text conditions (ICD-10-CM) and medications (RxNorm ingredient RXCUI) in this order, recording why each step was skipped in `warnings`:

1. Amazon Comprehend Medical `InferICD10CM` / `InferRxNorm`, with codes marked `code_source="comprehend_medical"` and the service's confidence.
2. A Bedrock coder (Strands agent, structured output, temperature 0), marked `code_source="llm"` with confidence capped at 0.85, so a model guess never outranks a printed or Comprehend code.
3. Uncoded text (`system="text"`), which still feeds the keyword-based risk flags.

PCP-summary medication names also go through the cascade, since the summary prints product names but no RxNorm codes.

## Output: `HistoryProfile`

```text
patient            id (MRN), gender, birth_date, age_years
conditions         CodedItem[]  display, code, system, status, onset, detail, confidence, code_source, source_ref
medications        CodedItem[]  status active|stopped, directions and prescriber in detail
allergies          CodedItem[]  reaction, criticality and category in detail
procedures         CodedItem[]
family_history     CodedItem[]  condition in display, relation and age at onset in detail
social_history     tobacco, alcohol, occupation, living situation, language, patient notes
care_team          provider display names seen in the history
known_specialists  lower-case specialties the patient already sees (primary_care, cardiology, ...)
risk_flags         ckd, diabetes, prediabetes, hypertension, liver, pregnancy, anticoagulant, heart_failure, ...
source             pdf | fhir | csv | intake_text | degraded
document_kind      for pdf: pcp_record | patient_questionnaire
no_known_allergies the source explicitly says no known allergies
warnings           parse problems and coding provenance; non-empty means review
summary            LLM-written, plain language
clinician_notes    LLM-written, up to 5 items
```

`source == "degraded"` means the input could not be parsed. Summarize then treats every abnormal finding as incidental, which is the conservative direction, and the LLM is not called.

## Risk flags and the expected-vs-incidental table

`risk_flags.py` holds small prefix tables for ICD-10-CM, ICD-9-CM and the SNOMED codes Synthea emits, plus display-text and medication-name keyword fallbacks. Only **active** conditions and medications contribute flags, so a resolved pregnancy or a stopped anticoagulant does not.

`EXPLAINS` maps each flag to the lab analytes and imaging labels it can explain. `explained_by("Glucose", profile)` returns `["diabetes"]` for a diabetic patient and `[]` otherwise. Summarize uses this to set `Finding.explained_by` or put the finding in the incidental ledger. `nsaid_excluded(profile)` is the Wellness hard filter from [SAFETY.md](SAFETY.md) rules 2 and 3.

All three tables are a labeled prototype rule set, not a clinical standard. `prediabetes` deliberately explains nothing, so a high or diabetes-range A1c in a known prediabetic stays actionable, which matches the bundled answer keys. The expected-vs-incidental rule in `data/tests/test_history.py` is mirrored on our side by `tests/test_pdf_cases.py`, which asserts that no parsed history explains an incidental radiology finding.

## Scorecard on the bundled cases (2026-10-23)

`scripts/eval_history.py` runs the agent over all 10 cases in `data/cases/` and scores it against each case's history block. Offline (`--offline`, no AWS) the 8 PCP summaries parse exactly: every ICD-10 code, status, note, medication, direction, allergy, criticality, procedure, family member, social line and care-team entry. Live, with Comprehend Medical denied on the test account so the Bedrock coder took over:

| Case | Kind | Conditions recall / precision | Med names | Med RxNorm match | Allergies | Summary |
|---|---|---|---|---|---|---|
| case_001 | pcp_record | 1.0 / 1.0 | 1.0 | 1.0 | 1.0 | yes |
| case_002 | pcp_record | 1.0 / 1.0 | 1.0 | 0.75 | 1.0 | yes |
| case_003 | pcp_record | 1.0 / 1.0 | 1.0 | 0.0 | 1.0 | yes |
| case_004 | questionnaire | 1.0 / 1.0 | 1.0 | 0.33 | 0.0 (see note) | yes |
| case_005 | pcp_record | 1.0 / 1.0 | 1.0 | 1.0 | 1.0 | yes |
| case_006 | questionnaire | n/a (none) | 1.0 | 1.0 | n/a (NKA) | yes |
| case_007 | pcp_record | 1.0 / 1.0 | 1.0 | 0.0 | 1.0 | yes |
| case_008 | pcp_record | 1.0 / 1.0 | 1.0 | 1.0 | 1.0 | yes |
| case_009 | pcp_record | n/a (none) | n/a | n/a | 1.0 | yes |
| case_010 | pcp_record | 1.0 / 1.0 | 1.0 | 1.0 | 1.0 | yes |

Notes: RxNorm matching compares the exact ingredient RXCUI, and the LLM coder sometimes returns a product-level or wrong RXCUI, which is why those codes are marked `code_source="llm"` and capped in confidence; Comprehend Medical is the intended primary coder. The case_004 allergy "Sulfa (Bactrim)" was captured as written with its reaction, but the scorer's ingredient match against "Sulfamethoxazole / trimethoprim" fails; allergies are kept as written on purpose. Each case took 6 to 18 seconds end to end.

## Running it

```bash
cd AgenticAIHackathonAWS
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q tests data/tests     # 180 tests, offline

# parse only (no AWS calls)
.venv/bin/python -m carerelay.history --pdf data/output/case_001/history.pdf --no-llm
.venv/bin/python -m carerelay.history --fhir data/samples/history/synthea_coherent_sample_bundle.json --no-llm
.venv/bin/python -m carerelay.history --mimic-dir data/samples/history/mimic_demo_subject_10004235 --subject 10004235 \
    --intake "Allergies: sulfa (hives)" --offline --no-llm

# full run: deterministic parse, then Bedrock writes summary and clinician notes
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0   # pick from the workshop allowlist
.venv/bin/python -m carerelay.history --pdf data/output/case_005/history.pdf --out profile.json
.venv/bin/python scripts/eval_history.py            # scorecard over all 10 cases (add --offline for no AWS)
```

From Python:

```python
from carerelay.history import build_history_profile, run_history_agent, make_history_agent

profile = build_history_profile(fhir_bundle="bundle.json")                 # no LLM
profile = run_history_agent(fhir_bundle="bundle.json", intake_text=text)   # with summary
agent = make_history_agent()                                               # Strands Agent for the graph
```

`make_history_agent()` returns a Strands `Agent` named `history` whose tools are `parse_history_pdf_file`, `parse_fhir_history`, `parse_mimic_history`, `parse_intake_history`, `derive_risk_flags` and `check_finding_explained`. In the CareRelay graph it is the third parallel entry node next to Lab and Radiology (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## AWS permissions and failure handling

| Call | Permission | On failure |
|---|---|---|
| Bedrock Converse (summary) | `bedrock:InvokeModel*` on the inference profile | Profile returned without summary, `warnings` gets `LLM summary unavailable: <error>` |
| Comprehend Medical `InferICD10CM`, `InferRxNorm` | `comprehendmedical:InferICD10CM`, `comprehendmedical:InferRxNorm` | Items kept as uncoded text, keyword flags still apply, warning recorded |

Both failure paths were exercised on 2026-10-23: a model the account could not access, and an IAM user without Comprehend Medical rights. Neither crashed the pipeline, which is guardrail 2 in [SAFETY.md](SAFETY.md).

## Known limits

- The PDF table parser is tuned to the layout `data/render.py` produces. A different portal's summary falls back to free-text intake parsing with a warning (`document_kind="unknown"`).
- Synthea Coherent patients were generated in 2022, so `age_years` computed today can be implausible. Pass `as_of` to `parse_fhir_bundle` for a fixed reference date.
- MIMIC "active" medications are the orders from the latest admission, not a verified discharge list.
- Specialty detection is keyword based. Synthea encounters rarely carry specialties, so `known_specialists` is often short for FHIR input and richer for the intake form.
- The intake parser never sends the allergies section to Comprehend Medical; allergies stay as written.
