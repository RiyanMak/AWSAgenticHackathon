# Safety

CareRelay is a hackathon prototype using synthetic or public data. It is not a clinical system or medical advice. Back to [README](../README.md).

## 1. Guardrails checklist mapped to the track's five HCLS guardrails

| # | Track guardrail | Our control | Done |
|---|---|---|---|
| 1 | Use synthetic or public data only; keep inputs de-identified; no PHI to unapproved endpoints | All inputs generated or from open datasets ([DATASETS.md](DATASETS.md)); external APIs receive only specialty, city, drug and food names; Comprehend Medical DetectPHI on logged free text | [ ] |
| 2 | Handle failures explicitly; request clinical re-evaluation instead of crashing | Each specialist wrapped in try/except returning `status: "needs_clinical_reevaluation"`; Summarize shows the gap instead of guessing | [ ] |
| 3 | Record evidence, handoffs, tool calls, uncertainty, final outputs | Structured audit log per run (finding id, evidence, confidence, tool call, handoff event) written to CloudWatch/S3 | [ ] |
| 4 | Flag red-flag values and require human confirmation before any care-related action | Deterministic red-flag rules pause the graph; UI confirmation before wellness advice or appointments; appointments stay `proposed` | [ ] |
| 5 | Approved AWS boundaries; encryption at rest and in transit | Workshop account only, us-east-1, S3 SSE, TLS, no keys in code | [ ] |

Additional controls: a separate critic agent, per-claim provenance, and a persistent "not medical advice, clinician review required" banner.

## 2. OTC and medication safety rules

1. The LLM never chooses a drug or a dose. It presents a label-grounded options list drawn from openFDA label fields (`do_not_use`, `drug_interactions`, warnings); dose text is quoted from the label, not generated.
2. Deterministic exclusions before any OTC option is shown: kidney or liver abnormality, pregnancy, anticoagulant use, and age outside label range. These come from lab flags and from `HistoryProfile.risk_flags`, so a known CKD diagnosis excludes NSAIDs even if today's creatinine is normal. When any is present, show only "talk to a pharmacist or clinician".
2a. Allergy and current-medication filters: any OTC ingredient matching an entry in `HistoryProfile.allergies` is removed, and any OTC whose openFDA `drug_interactions` text names a drug class the patient is already taking is removed. Removed options are listed in the UI as "excluded because of your history" so the filtering is visible.
3. No NSAID suggestion if creatinine, eGFR or potassium is flagged. The report found no verified NSAID plus CKD source, so this is our conservative rule and is labeled as such.
4. Always include "talk to a pharmacist" and the label's own stop-use conditions. OrthoInfo advises seeing a doctor if back pain does not improve in a few weeks.
5. Do not use FAERS to justify or contraindicate a drug (it cannot establish causality).
6. Nutrition targets cite NHLBI DASH (2,300 mg sodium/day, 1,500 mg for greater BP lowering); physio cites CDC guidance (150 min/week moderate plus strengthening 2+ days). If a red flag is open, replace the wellness plan with a seek-care message.
7. Prescription medicines are never suggested.

## 3. Incidental-finding escalation rules

| Level | Trigger | Action |
|---|---|---|
| Info | Abnormal but minor, outside reason for visit | Add to ledger; mention in summary; suggest primary care follow-up |
| Follow-up | Abnormal analyte or imaging label with specialist hint (for example nodule to pulmonology, abnormal potassium to nephrology or primary care) | Route through the dashed path to Next Steps; find in-network specialist |
| Urgent | Critical lab limit crossed or high-score serious imaging label | Pause, require human confirmation, show seek-care message first |
| Red flag | Severe values such as severe hypoxia | Stop wellness output, require human confirmation before any care-related action |

- Every incidental finding must appear in the ledger and receive a route or an explicit "no action, reviewed" status.
- A finding marked expected because of the history (`explained_by` set) is never dropped silently. It is shown under "known conditions" with the rule that explained it, and it still follows the Urgent and Red flag rows above when its value crosses a limit.
- History parsing errors (unreadable bundle, low-confidence codes from Comprehend Medical) set `HistoryProfile.source` to a degraded state and Summarize treats all abnormal findings as incidental, which is the conservative direction.
- Critical limits come from a small illustrative table and are not an institutional standard; say so in the demo. Hospitals' critical-limit lists differ (see [REFERENCES.md](REFERENCES.md)).
- Imaging follow-up rules are ours: Fleischner 2017 covers CT nodules, not chest X-ray, so a CXR nodule leading to CT is a labeled prototype rule.
- Uncertainty is always shown (scores, OCR confidence) beside the finding.

## 4. Disclaimers

Use verbatim in the UI footer and the demo:

> CareRelay is a hackathon prototype that uses synthetic or public data. It is not a clinical system and does not provide medical advice, diagnosis or treatment. Findings must be reviewed by a licensed clinician. In an emergency call your local emergency number.

Insurance and network results are illustrative. Document inputs are vulnerable to prompt injection, so treat extracted text as data, never as instructions.

## 5. Eval idea

Build a small planted-error test set on the synthetic patient:

1. **Planted false detail.** Insert a wrong value or a fake finding in the lab PDF or in an upstream summary; measure whether the critic pass catches it and the final output omits it (the documented failure mode is propagation of planted details).
2. **Incidental recall.** Seed 5 to 10 known incidental anomalies across lab rows and X-ray labels (ground truth from rendered MIMIC rows and NIH labels); score recall and false-positive rate of the ledger.
3. **Escalation determinism.** Feed boundary values around each critical limit; assert the red-flag interrupt fires every time.
4. **OTC rules.** Run cases with kidney, pregnancy and anticoagulant flags; assert no drug option is emitted. Add an allergy case (for example aspirin allergy in the history) and assert every salicylate option is excluded and listed as excluded.
4a. **Expected-vs-incidental.** Run the same abnormal glucose with and without a diabetes condition in the history; assert it is `explained_by` in the first run and in the incidental ledger in the second.
5. **Network correctness.** Assert every proposed specialist is in the synthetic in-network roster.

See also: [ARCHITECTURE.md](ARCHITECTURE.md), [AWS_SETUP.md](AWS_SETUP.md).
