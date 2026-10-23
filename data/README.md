# data

Synthetic inputs for the care-team pipeline: 10 patient cases (radiology PDF, matching lab PDF and medical history PDF), a mocked insurance and provider network, and deterministic tools over it. Everything is fictional. Hackathon prototype, not medical advice.

From the repo root (there is no pyproject yet, so dependencies are passed with `--with`):

```bash
uv run --with reportlab python data/build.py   # regenerate output/ and CASES.md
uv run --with reportlab --with pytest pytest data   # network math + case integrity checks
```

Rebuilding reproduces the JSON and CASES.md byte for byte; PDF bytes change (embedded metadata) but content does not.

See [CASES.md](CASES.md) for the scenario index.

## Layout

| Path | What it is |
|---|---|
| `cases/case_*.json` | Source of truth per case. FHIR-shaped `Patient`, `Coverage`, `DiagnosticReport`; `labs` (values only); `history` (conditions, medications, allergies, procedures, family and social history, care team); `intake` answers; `answer_key` (ground truth, never shown to agents). |
| `output/<case>/radiology.pdf`, `labs.pdf`, `history.pdf` | What the patient uploads. `history.pdf` is a PCP "Patient Health Summary" (coded) or, for patients with no PCP (case_004, case_006), a patient-typed "Patient Health Questionnaire" (uncoded). |
| `output/<case>/intake_expected.json` | What the Intake agent should produce: FHIR-shaped resources (including `History`: Condition, MedicationStatement, AllergyIntolerance, Procedure, FamilyMemberHistory, social-history Observation, CareTeam) plus intake answers, no answer key. |
| `reference/lab_catalog.json` | Lab panels, units, reference ranges, lab facilities. Flags (H/L/A) are computed from these. |
| `network/plans.json` | 4 plans: PPO, HMO (referrals), Medicare Advantage HMO (copays), HDHP. Benefits by service category, prior auth, out-of-network rules. |
| `network/services.json` | Service catalog keyed by id (`ct_chest_wo`, `visit_pulmonology`, ...): category, allowed amount, minutes. Answer keys use these ids. |
| `network/providers.json` | 33 Austin-area providers: networks, services, hours, lead time, booking density, price factor, languages. |
| `network/member_accumulators.json` | Mock payer lookup: deductible and OOP spent so far, by member ID. |
| `network.py` | Tools: `find_providers`, `find_slots`, `estimate_cost`, `requires_prior_auth`, `requires_referral`, `get_member`, `to_appointment`. |
| `labs.py`, `history.py`, `render.py`, `build.py` | Lab flagging and FHIR output, history FHIR output, PDF rendering, build script. |

## Notes

- `estimate_cost` prices one service against the member's current accumulators. To price a sequence of follow-ups, the caller adds each result to `deductible_met`/`oop_met` before pricing the next.
- `find_slots` is deterministic for a given start date (the booked or free state comes from a hash), so demos are repeatable. Use `2026-10-23` as "today".
- Guideline text (Fleischner, ACR, Lung-RADS, SVS) is paraphrased for realism and not clinically reviewed.
- History codes: ICD-10-CM codes were checked against the NLM Clinical Tables API and RxNorm codes against RxNav (2026-10-23). RxNorm codes are ingredient-level (IN, or MIN for combinations), not product-level. Procedures are text only (CPT and SNOMED need licenses).
- The history never codes a condition that would explain a finding the answer key marks incidental (`tests/test_history.py` enforces this with a small rule table). Medications started in the ED (case_002 tamsulosin) are in `intake` but not yet in the PCP record.
- Allergies chosen to matter for Wellness OTC filtering: case_001 dextromethorphan (excludes "DM" cough products), case_007 ibuprofen with lip swelling (high criticality, excludes NSAIDs; mildly high ALT also limits acetaminophen), case_010 shellfish (nutrition plan).
