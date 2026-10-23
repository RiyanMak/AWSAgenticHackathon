# Wellness Agent

Budget nutrition, activity and label-grounded OTC options while the patient waits for a specialist. Implements the Wellness row of [ARCHITECTURE.md](../../docs/ARCHITECTURE.md) and the rules in [SAFETY.md](../../docs/SAFETY.md) section 2.

| File | Role |
|---|---|
| `rules.py` | Deterministic plan: red-flag gate, OTC exclusions, DASH nutrition, CDC activity. Source of truth. |
| `knowledge.py` | Hand-authored prototype rule tables (candidates, allergy classes, label terms, staples). |
| `clients.py` | openFDA label and FoodData Central lookups with bundled snapshot fallback. |
| `agent.py` | Strands `Agent` (node id `wellness`) that explains the plan; narrative check and template fallback. |
| `data/` | Snapshots written by `scripts/refresh_wellness_snapshots.py`. |

## Run

```bash
python -m pytest -q                                                        # offline safety tests
python -m carerelay.wellness.agent examples/wellness_demo_case.json --no-model   # template text
BEDROCK_MODEL_ID=us.openai.gpt-5.6-luna python -m carerelay.wellness.agent examples/wellness_demo_case.json
python scripts/refresh_wellness_snapshots.py                               # set FDC_API_KEY first
```

`CARERELAY_OFFLINE=1` skips live openFDA calls and uses the snapshot.

The bundled cases from main (`data/cases/`) load through the stand-in adapter `carerelay/dev_cases.py` (`load_case("case_001")`). It builds lab findings from `data/labs.py` flags, leaves out radiology findings, uses a tiny risk-flag table and never reads `answer_key`. Replace it with real Summarize output once that exists. `tests/test_wellness_bundled_cases.py` checks the Wellness-relevant allergies called out in `data/README.md`.

## Graph integration

```python
wellness = make_wellness_agent()
wellness.state.set("case_record", case_record.model_dump(mode="json"))  # before the node runs
g.add_node(wellness, "wellness")
```

Graph nodes in Strands 0.3.0 receive only upstream text, so the `CaseRecord` goes through agent state. The tool also accepts it as a JSON argument.

## Behavior

- Red flag open: plan replaced by a seek-care message, even after confirmation. Urgent: withheld until `human_confirmed`, then shown after a seek-care message.
- OTC candidates come from visit-reason keywords (pain, fever, heartburn, cough). OTC is pharmacist-only when there is a ckd, liver, pregnancy or anticoagulant risk flag, a flagged kidney or liver lab, unknown or under-18 age, a degraded history, or a visit reason that needs a clinician first (chest pain, shortness of breath, trauma, a fall, numbness, and so on). That last group also limits activity to gentle.
- Per-option exclusions (all listed as "excluded because of your history"): allergy class (aspirin allergy also excludes NSAIDs), duplicate class, NSAIDs when potassium is flagged, label `do_not_use`/`ask_doctor` text naming a current medicine or condition (including smoking or emphysema for dextromethorphan), and "do not use for persistent or chronic" symptoms.
- Directions are quoted verbatim from the openFDA label. The model never chooses a drug or dose, and a narrative naming any medicine outside the plan is replaced by the template.
- Nutrition: 1,500 mg sodium with hypertension, else 2,300 (DASH). Carb guidance for diabetes or a flagged glucose, and a potassium caution for CKD or flagged potassium. Both are prototype rules. Food allergens filter the staples.
- Activity: CDC 150 min/week plus strength on 2+ days, or gentle only when a finding or condition is cardiopulmonary.

Prototype rules, not a clinical standard.
