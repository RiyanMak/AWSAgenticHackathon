# Datasets

Only sources verified in [the research report](research/deep_research_report.md) are listed. Rows marked **(medium)** survived verification only with a correction or lower confidence. Back to [README](../README.md).

Rule of thumb: render synthetic inputs ourselves so ground truth is exact, and download only small subsets.

## 1. Lab PDFs

No open dataset of lab-report PDFs with ground truth was found. Best approach: render rows from the datasets below into PDFs with a template (reportlab or HTML-to-PDF).

| Name | Link | Contains | License / access | Size | Download | How we use it |
|---|---|---|---|---|---|---|
| MIMIC-IV Clinical Database Demo v2.2 | [PhysioNet](https://physionet.org/content/mimic-iv-demo/2.2/) | 100 patients; `hosp/labevents.csv.gz` with `ref_range_lower`, `ref_range_upper`, `flag`; `d_labitems.csv.gz` | ODbL v1.0, open, no credentialing (attribution needed) | 15.5 MB (labevents 1.9 MB, d_labitems 13.2 KB) | Download the zip from the [dataset page](https://physionet.org/content/mimic-iv-demo/2.2/) or its [hosp folder](https://physionet.org/content/mimic-iv-demo/2.2/hosp/) | Primary lab source: pick one patient, render `labevents` to a PDF with reference ranges |
| Synthea | [GitHub](https://github.com/synthetichealth/synthea) | Synthetic patients; `observations.csv` has LOINC code, description, value, units, type (no reference range column) | Apache-2.0 | Generated on demand | Clone the repo and run the generator with CSV export enabled (off by default); see the [CSV data dictionary](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary) | License-clean second source; pair with our own range table |
| Synthea Coherent Data Set | [AWS registry](https://registry.opendata.aws/synthea-coherent-data/) | Linked synthetic FHIR R4 bundles, DICOM, ECG, DNA, notes per patient | CC BY 4.0, open | 9.2 GB zip; `fhir/` 1,281 objects, `dicom/` 299 | `aws s3 ls --no-sign-request s3://synthea-open-data/coherent/` | Optional single linked patient (labs plus imaging); sync one folder, not the zip |
| eICU Collaborative Research Database Demo v2.0.1 | [PhysioNet](https://physionet.org/content/eicu-crd-demo/2.0.1/) | ICU EHR incl. `lab`, `customLab` tables | ODbL 1.0, open | 130.4 MB | HTTPS zip from the page (S3 prefix was empty on test day) | Fallback if MIMIC demo is awkward |
| JohnSnowLabs pdf-deid-dataset **(medium)** | [GitHub](https://github.com/JohnSnowLabs/pdf-deid-dataset) | Synthetic PDFs, Easy/Medium/Hard, includes a "Medical Tests" layout; page counts inconsistent | No license stated, check LICENSE before reuse | About 50 PDFs | `git clone https://github.com/JohnSnowLabs/pdf-deid-dataset` | OCR robustness tests only |
| constellation `labs` table | [CRAN docs](https://search.r-project.org/CRAN/refmans/constellation/html/labs.html) | 3,150-row, 96-patient synthetic table, 6 analytes | See CRAN package | Tiny | Install the R package and export the table | Tiny fallback only |

## 2. X-rays

| Name | Link | Contains | License / access | Size | Download | How we use it |
|---|---|---|---|---|---|---|
| NIH ChestX-ray14 (HF mirror) | [HF dataset](https://huggingface.co/datasets/alkzar90/NIH-Chest-X-ray-dataset) | 112,120 frontal PNGs, 30,805 patients, 14 labels, no reports | Card quotes NIH as imposing no restrictions beyond attribution; HF metadata says "unknown"; community mirror | 45.1 GB total, take a subset | `datasets.load_dataset("alkzar90/NIH-Chest-X-ray-dataset", streaming=True)` (check the card for config names) | Demo X-ray with a known label as ground truth |
| NIH ChestX-ray14 (Kaggle, linked by the track) | [Kaggle](https://www.kaggle.com/datasets/nih-chest-xrays/data) | Same data | Kaggle account | Large | Kaggle download | Alternative source |
| InRad COVID-19 CXR/CT | [AWS registry](https://registry.opendata.aws/inlab-covid-19-images-dataset/) | Anonymized COVID-19 chest X-ray and CT images | CC BY 4.0, anonymous access | See registry | `aws s3 ls --no-sign-request --region us-west-2 s3://inlab-opendata-covid-anonymized-images/` | AWS-resident images for pipeline tests |
| Open-i / Indiana University CXR **(medium)** | [HF mirror](https://huggingface.co/datasets/ykumards/open-i) | Images with findings and impression reports | Non-commercial (mirror lists CC BY-NC-ND 4.0); official site was down on test day | About 7,470 to 8,121 images (sources disagree) | Kaggle or HF download | Only if report text is wanted; mirror specs were refuted in verification, check before use |
| RSNA Pneumonia Detection Challenge 2018 | [RSNA](https://www.rsna.org/education/ai-resources-and-training/ai-image-challenge/rsna-pneumonia-detection-challenge-2018) | 26,684 DICOM CXRs with pneumonia boxes | Kaggle terms are non-commercial; RSNA page allows attribution use; free account | Large | Kaggle download | Real DICOM source if DICOM tooling is needed |
| Synthea Coherent DICOM | [AWS registry](https://registry.opendata.aws/synthea-coherent-data/) | Synthetic DICOM linked to FHIR patients | CC BY 4.0 | See section 1 | `aws s3 ls --no-sign-request s3://synthea-open-data/coherent/` | HealthImaging import demo (optional) |
| TorchXRayVision (model) | [GitHub](https://github.com/mlmed/torchxrayvision) | `densenet121-res224-all`, 18 pathology scores | Apache-2.0, no gating | Small, CPU feasible | `pip install torchxrayvision` | Deterministic label scores for the Radiology Agent |
| MedGemma 4B IT (model) | [HF](https://huggingface.co/google/medgemma-4b-it) | Medical VLM incl. chest X-rays | Gated, accept terms on HF; not for clinical use | 4B params | Needs GPU self-host | Optional, only if a GPU endpoint is quickly available |
| CheXagent-2-3b (model) **(medium)** | [HF](https://huggingface.co/StanfordAIMI/CheXagent-2-3b) | Chest X-ray VLM | MIT tag today, earlier notes said research-only; re-read card | 3B params | Needs `trust_remote_code=True` | Optional; resolve license first |

Not usable today: VinDr-CXR ([PhysioNet](https://physionet.org/content/vindr-cxr/1.0.0/)) and MIMIC-CXR-JPG ([PhysioNet](https://physionet.org/content/mimic-cxr-jpg/2.1.0/)) need PhysioNet credentialing, CITI training and a DUA. MAIRA-2 ([HF](https://huggingface.co/microsoft/maira-2)) and LLaVA-Rad ([HF](https://huggingface.co/microsoft/llava-rad)) are research-only.

## 3. Medical history

No new dataset is needed. The lab sources in section 1 already carry history for the same synthetic patient, which keeps labs and history consistent.

| Name | Link | Contains | License / access | Size | Download | How we use it |
|---|---|---|---|---|---|---|
| Synthea FHIR R4 bundles | [GitHub](https://github.com/synthetichealth/synthea) | Per-patient bundles with `Condition`, `MedicationRequest`, `AllergyIntolerance`, `Procedure`, `Encounter`, `Immunization`, all coded (SNOMED, RxNorm) | Apache-2.0 | One JSON file per patient, typically under 1 MB | Run the generator with FHIR export (the default) or pull one patient folder from the Coherent set below | Primary history source: parse deterministically into `HistoryProfile` |
| Synthea Coherent Data Set | [AWS registry](https://registry.opendata.aws/synthea-coherent-data/) | Same FHIR bundles linked to DICOM, ECG and clinical notes for one patient | CC BY 4.0, open | `fhir/` 1,281 objects | `aws s3 cp --no-sign-request s3://synthea-open-data/coherent/fhir/<patient>.json .` | Linked patient when labs, imaging and history should all agree |
| MIMIC-IV Clinical Database Demo v2.2 | [PhysioNet](https://physionet.org/content/mimic-iv-demo/2.2/) | `hosp/diagnoses_icd.csv.gz` plus `d_icd_diagnoses.csv.gz` (ICD-9/10 conditions), `hosp/prescriptions.csv.gz` (medications), `hosp/procedures_icd.csv.gz` | ODbL v1.0, open | Included in the 15.5 MB zip from section 1 | Same download as section 1 | History for the same patient whose labs we render; no allergy table, so allergies come from the intake form |
| Typed intake form (ours) | n/a | Free-text conditions, medications, allergies, surgeries, current doctors | Ours | n/a | A short form in the demo UI | Free-text path through Comprehend Medical InferICD10CM and InferRxNorm; also the only allergy source for MIMIC patients |
| Synthea CSV export | [CSV data dictionary](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary) | `conditions.csv`, `medications.csv`, `allergies.csv`, `procedures.csv`, `encounters.csv` | Apache-2.0 | Generated on demand | Enable CSV export in the generator config | Flat-file alternative if FHIR parsing is slow to write |

## 4. Insurance cards

No public insurance card image dataset with a verified license was found. Generate synthetic cards (PIL or HTML) with fake member ID, group, payer, plan name, Rx BIN/PCN/GRP and copays.

| Name | Link | Contains | License / access | Size | Download | How we use it |
|---|---|---|---|---|---|---|
| Synthetic cards (ours) | n/a | Generated PNG/JPEG cards | Ours | A few files | Generate with a small PIL script ([TODO](TODO.md) step 3) | Exact ground truth for the Insurance Agent |
| carecard | [GitHub](https://github.com/singh318683/carecard) | Code that sends a card photo to Claude | No license file, reference only | Small repo | `git clone` to read | Prompt and field-schema ideas |
| InsuranceCardReader | [GitHub](https://github.com/lalamander/InsuranceCardReader) | OCR reader | GPL-3.0, appears to contain an exposed service-account key | 2 commits | Avoid | Do not use |
| Mindee US health insurance card OCR | [Mindee](https://www.mindee.com/product/us-health-insurance-cards-ocr-api) | Field list returned by a commercial API | 14-day trial, signup needed | n/a | n/a | Reference for which fields to extract |
| Waystar payer list | [Waystar](https://login.zirmed.com/ui/Payers) | Payer names and IDs, Download (.CSV) link | Login requirement not stated | n/a | Use the page's CSV link | Seed the card-to-payer lookup |
| Third-party payer ID list **(medium)** | [medicalbillingrcm.com](https://medicalbillingrcm.com/insurance-payer-id-list-medical-billing/) | UnitedHealthcare 87726, Aetna 60054, Cigna 62308; unofficial, mixed dates | Unofficial | n/a | n/a | Cross-check only |

## 5. Knowledge sources

| Name | Link | Contains | License / access | How we use it |
|---|---|---|---|---|
| MIMIC labevents docs | [docs](https://mimic.mit.edu/docs/iv/modules/hosp/labevents) | Column definitions incl. reference ranges and `flag` (no trailing slash) | Open docs | Lab flag logic |
| MedlinePlus reuse policy **(medium)** | [policy](https://medlineplus.gov/about/using/usingcontent/) | NLM content is public domain with credit; A.D.A.M. and ASHP content is copyrighted | See policy | Patient-friendly wording sources, link rather than copy |
| Critical limits article **(medium)** | [MLO](https://www.mlo-online.com/diagnostics/article/55303948/table-of-critical-limits) | Comparison of 2024 hospital critical-limit lists | Publisher | Background only; hardcode a small illustrative table and label it as such |
| Cleveland Clinic incidental finding | [page](https://my.clevelandclinic.org/health/diagnostics/incidental-finding) | Definition of incidental finding | Link only | Operational definition |
| ACR Incidental Findings | [ACR](https://www.acr.org/Clinical-Resources/Clinical-Tools-and-Reference/Incidental-Findings) | Committee white papers (full text may be paywalled) | Link only | Reference for escalation rules |
| Fleischner 2017 | [PubMed](https://pubmed.ncbi.nlm.nih.gov/28240562/) | Incidental nodules on CT, not chest X-ray | Link only | Our CXR-nodule to CT follow-up rule is our own, labeled as such |
| openFDA drug label | [docs](https://open.fda.gov/apis/drug/label/) | Rx and OTC labels, JSON | Free key recommended | OTC "do not use if", interactions |
| USDA FoodData Central | [API guide](http://fdc.nal.usda.gov/api-guide/) | Nutrient data | CC0 data, data.gov key | Budget nutrition |
| NHLBI DASH | [page](https://www.nhlbi.nih.gov/education/dash-eating-plan) | 2,300 mg sodium/day (1,500 mg for greater BP lowering) on 2,000 kcal | Public | Nutrition targets |
| CDC adult activity guidelines | [page](https://www.cdc.gov/physical-activity-basics/guidelines/adults.html) | 150 min/week moderate plus strengthening 2+ days | Public | Physio baseline |
| OrthoInfo low back pain | [page](https://www.orthoinfo.org/en/diseases--conditions/low-back-pain/) | Acetaminophen and NSAID options, see a doctor if no improvement in weeks | AAOS copyright, link do not copy | Physio and OTC grounding |
| wger exercises | [GitHub](https://github.com/wger-project/wger) | Exercise database | Code AGPL-3.0+, data CC per entry | Optional exercise lookup |
| NUCC taxonomy | [NUCC](https://www.nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40) | Provider taxonomy codes (CSV/PDF) | License needed for commercial products | Specialty to taxonomy map; verify codes at taxonomy.nucc.org |
| CMS Doctors and Clinicians file | [CMS](https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/mj5m-pzi6) | One row per clinician/enrollment/address, public CSV | License not stated | Optional offline specialist roster |
| Da Vinci PDEX Plan-Net v1.2.0 | [HL7](https://hl7.org/fhir/us/davinci-pdex-plan-net/) | FHIR R4 provider directory spec | Open spec | Network roster model |

Skipped as too heavy for one day: CMS price-transparency files ([schemas](https://github.com/CMSgov/price-transparency-guide), [Centene files](https://www.centene.com/price-transparency-files.html)).

See also: [APIS.md](APIS.md), [REFERENCES.md](REFERENCES.md).
