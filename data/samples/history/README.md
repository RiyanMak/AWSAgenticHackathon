# Sample medical history inputs

Small, open-licensed samples so the History Agent and its tests run offline. Both are synthetic or de-identified; neither contains real patient data.

| File | Source | License | Notes |
|---|---|---|---|
| `synthea_coherent_sample_bundle.json` | One patient from the [Synthea Coherent Data Set](https://registry.opendata.aws/synthea-coherent-data/) (`s3://synthea-open-data/coherent/unzipped/fhir/`), trimmed to Patient, Condition, MedicationRequest, AllergyIntolerance, Procedure, CareTeam and the first six Encounters | CC BY 4.0 | Fully synthetic. Walonoski J, et al. "The Coherent Data Set." Electronics 2022, 11(8), 1199. |
| `mimic_demo_subject_10004235/` | Rows for one subject from the [MIMIC-IV Clinical Database Demo v2.2](https://physionet.org/content/mimic-iv-demo/2.2/) `hosp` tables (`patients`, `diagnoses_icd`, `prescriptions`, `procedures_icd`) plus the matching rows of `d_icd_diagnoses` and `d_icd_procedures` | ODbL 1.0 | De-identified, dates shifted. Johnson A, et al. MIMIC-IV Clinical Database Demo (version 2.2). PhysioNet. https://doi.org/10.13026/dp1f-ex47 |

Regenerate with the full MIMIC demo zip and any Coherent bundle:

```bash
aws s3 cp --no-sign-request "s3://synthea-open-data/coherent/unzipped/fhir/<patient>.json" bundle.json
curl -L -o mimic-demo.zip https://physionet.org/static/published-projects/mimic-iv-demo/mimic-iv-clinical-database-demo-2.2.zip
unzip mimic-demo.zip '*/hosp/*'
```

Then filter to one `subject_id` and trim the bundle to the resource types above.
