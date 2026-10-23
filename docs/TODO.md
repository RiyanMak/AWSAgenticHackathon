# Build TODO (hackathon day)

Ordered checklist with time boxes, assuming one build day. Adjust to the event schedule. Back to [README](../README.md).

| # | Task | Time box | Done |
|---|---|---|---|
| 1 | Join Workshop Studio, open VS Code, verify `WSParticipantRole` ([AWS_SETUP.md](AWS_SETUP.md)) | 20 min | [ ] |
| 2 | Run starter kit: `infer.py` smoke test, check model allowlist (Sonnet 5.5, Nova, GPT profiles), test image and PDF input | 30 min | [ ] |
| 3 | Fix the demo patient: pick a case from [data/CASES.md](../data/CASES.md) (case_001 is the hero case; lab PDF, report PDF, history PDF and coverage are done). Remaining: pick one NIH CXR with a known label if showing an image, generate one synthetic insurance card from the case's `Coverage` ([DATASETS.md](DATASETS.md)) | 20 min | [ ] |
| 4 | Lab Agent: typed extraction, deterministic range comparator, incidental tag | 45 min | [ ] |
| 5 | Radiology Agent: TorchXRayVision scores plus Bedrock narrative, incidental tag | 45 min | [ ] |
| 6 | History Agent: FHIR or CSV parser into `HistoryProfile`, `risk_flags` table, Comprehend Medical path for the intake form ([HISTORY_AGENT.md](HISTORY_AGENT.md)) | done | [x] |
| 7 | Strands Graph: parallel Lab, Radiology and History, all-complete fan-in to Summarize ([ARCHITECTURE.md](ARCHITECTURE.md)) | 30 min | [ ] |
| 8 | Summarize: merged `CaseRecord`, expected-vs-incidental rule table, incidental ledger, critic pass, red-flag interrupt | 50 min | [ ] |
| 9 | Next Steps: specialty map, known-specialist shortcut, NPI search, Insurance tool with synthetic roster (optionally Plan-Net), `proposed` Appointment on HAPI ([APIS.md](APIS.md)) | 60 min | [ ] |
| 10 | Wellness Agent: openFDA-grounded OTC rules with allergy and current-medication filters, DASH nutrition shaped by history conditions, CDC physio ([SAFETY.md](SAFETY.md)) | 50 min | [ ] |
| 11 | Deploy: lane C Streamlit first, then lane A Lambda URL, then lane B AgentCore ([AWS_INFRASTRUCTURE.md](AWS_INFRASTRUCTURE.md); scaffolding and scripts are in `aws/`) | 45 min | [ ] |
| 12 | Eval pass: planted-error test, incidental recall, expected-vs-incidental pair, OTC exclusion and allergy cases | 30 min | [ ] |
| 13 | Rehearse the 3-beat demo, record backup run | 30 min | [ ] |
| 14 | Cleanup: delete runtimes, roles, buckets ([AWS_SETUP.md](AWS_SETUP.md)); push repo | 15 min | [ ] |

Cut order if behind: AgentCore Gateway, Plan-Net live query, wger, Comprehend Medical free-text path (keep FHIR/CSV history only), critic pass polish, HealthImaging.
