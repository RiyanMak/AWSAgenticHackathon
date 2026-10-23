# Deep Research Report: Multi-Agent Lab, Imaging and Follow-Up Navigator

**Event:** AWS Austin Agentic AI Hackathon, Track 1 (Caregivers Challenge), 2026-10-23, one build day, Workshop Studio AWS account, us-east-1, Bedrock + AgentCore + Strands.
**Research date:** 2026-10-23. All URLs below were reported as loading when fetched on that date unless flagged "not fetched". Claims marked **(medium)** survived verification only with a correction or lower confidence. Items cited as "earlier notes" come from the track-wide research summarized in [track1_background_report.md](track1_background_report.md).

> This is a hackathon prototype using synthetic or public data only. It is not a clinical system or medical advice, and the demo should say so explicitly (track guardrail, per earlier notes: `track_page_contents.md`).

## 1. Pipeline under study

```
Inputs: lab PDF, X-ray, insurance card
   |-> Lab Agent   (flags incidental anomalies) --\
   |-> Radiology Agent (flags incidental anomalies) --> Summarize node
Summarize --> Wellness Agent (budget nutrition, physio, OTC options while waiting)
Summarize --> Next Steps <--> Insurance Agent  (Scheduling Agent + Insurance Agent find in-network specialists
Summarize --(dashed: incidental findings)--> Next Steps   for expected AND incidental findings)
```

Lab and Radiology run in parallel; Next Steps and Insurance collaborate bidirectionally.

## 2. Fit with the official track (earlier notes)

- The track page asks for five personas (Lab Analyst, Radiologist, Doctor, Nutritionist, Physio) over labs, radiology images and EKG time series, with at least two visible specialist handoffs, one patient scenario and a patient-facing result (earlier notes: `track_page_contents.md`, citing [Track 1](https://atx.rahman.dev/track-1.html)).
- Your plan maps well: Lab = Lab Analyst, Radiology = Radiologist, Summarize = Doctor, Wellness = Nutritionist + Physio. Insurance and Scheduling are an extension beyond the listed personas. EKG is not in your diagram; adding it is optional (earlier notes: PTB-XL, CC BY 4.0, public S3).
- The track's HCLS guardrails (earlier notes): synthetic data only, explicit failure handling that requests clinical re-evaluation, audit trail of evidence/handoffs/tool calls/uncertainty, red-flag values requiring human confirmation, encryption at rest and in transit. Design the Summarize node around these.
- Judging criteria are not published (earlier notes). Prior-project patterns that recur: a separate critic/safety agent, per-claim provenance, deterministic escalation rules, human sign-off (earlier notes: `prior_projects_and_patterns.md`).

---

## 3. Input / ingestion (PDF, X-ray image, insurance card)

**What works on AWS.** Three routes exist for reading the lab PDF.
1. *Textract.* [AnalyzeDocument with TABLES](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-tables.html) returns TABLE and CELL blocks with column headers, merged cells, titles and footers, which suits lab grids. Synchronous PDF/TIFF is limited to 1 page and 10 MB; async accepts up to 500 MB and 3,000 pages ([quotas](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html)). [Queries](https://docs.aws.amazon.com/textract/latest/dg/queryresponse.html) return QUERY/QUERY_RESULT blocks with confidence.
2. *Bedrock Data Automation (BDA).* Synchronous documents accept PDF/TIFF/JPEG/PNG up to 10 pages and 50 MB; async up to 500 MB; blueprints max 100 leaf fields ([limits](https://docs.aws.amazon.com/bedrock/latest/userguide/bda-limits.html)). A project can hold one image blueprint and up to 40 document blueprints ([custom output](https://docs.aws.amazon.com/bedrock/latest/userguide/bda-custom-output-idp.html)). Whether BDA is available in the Workshop Studio account's us-east-1 was not verified.
3. *Send the PDF straight to a Bedrock model.* The Converse [DocumentBlock](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_DocumentBlock.html) accepts pdf, csv, doc, docx, xls, xlsx, html, txt and md; the `name` field allows only alphanumerics, single spaces, hyphens, parentheses and square brackets (max 200 chars), so sanitize "labs.pdf", and AWS warns it is vulnerable to prompt injection. Strands passes PDFs as document blocks with bytes or an S3 location ([Strands Bedrock provider](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/amazon-bedrock/)).
4. *Insurance card photo.* [Textract AnalyzeID](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-identity.html) documents passports, US driver licenses and government IDs, not insurance cards, so do not plan on it. The [Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html) accepts ImageBlock bytes, so a vision model can read the card directly; BDA sync images must be JPEG/PNG at most 5 MB.

**Pricing (Oregon rates; us-east-1 not shown on the pages).** Textract: Detect Text $0.0015, Tables $0.015, Forms $0.05, Queries $0.015 per page, AnalyzeID $0.025 ([Textract pricing](https://aws.amazon.com/textract/pricing/)). BDA: standard $0.010/page; custom $0.040/page for 30 or fewer fields plus $0.0005 per extra field; $0.005/image ([Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)). At demo volumes cost is negligible.

**Insurance-card inputs.** No public insurance card image dataset with a verified license was found; a Roboflow Universe listing was seen in search only (403 on fetch). Generate synthetic cards with PIL or HTML. Reference code: [singh318683/carecard](https://github.com/singh318683/carecard) (sends a card photo to Claude, no license file, reference only); [lalamander/InsuranceCardReader](https://github.com/lalamander/InsuranceCardReader) (GPL-3.0, 2 commits, appears to contain an exposed service-account key, avoid); commercial option [Mindee](https://www.mindee.com/product/us-health-insurance-cards-ocr-api) (14-day trial, signup needed).

**PHI/prompt safety.** [Bedrock Guardrails sensitive-information filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html) can BLOCK or ANONYMIZE PII in text but do not evaluate tool-call arguments or toolResult content, and trace match fields and invocation logs retain raw PII. [Comprehend Medical DetectPHI](https://docs.aws.amazon.com/comprehend-medical/latest/dev/textanalysis-phi.html) returns typed entities with offsets and scores for text only and recommends human review. Since data is synthetic, treat these as defense-in-depth, not a requirement.

### Recommended picks (ingestion)
1. Send lab PDFs and card images directly to a Bedrock multimodal model via Converse, with Textract TABLES as a fallback for dense lab grids (fewest moving parts for one day).
2. Generate synthetic insurance cards and lab PDFs yourself so ground truth is exact.
3. Use BDA only if time remains and availability is confirmed in the account.

### Gaps / unverified
- Textract and BDA us-east-1 prices, and BDA availability in the Workshop Studio account.
- Official Converse limits (4.5 MB / 5 documents) confirmed only via third parties.
- Per-model PDF support: the Sonnet 5.5 card lists Image and Text input only, with no explicit Document row; test PDFs or render pages to images.

---

## 4. Lab Agent

**Data.**
- [MIMIC-IV Clinical Database Demo v2.2](https://physionet.org/content/mimic-iv-demo/2.2/): 100 patients, 15.5 MB, ODbL v1.0, open with no credentialing (full MIMIC-IV needs credentialing). The [hosp folder](https://physionet.org/content/mimic-iv-demo/2.2/hosp/) contains `d_labitems.csv.gz` (13.2 KB) and `labevents.csv.gz` (1.9 MB).
- [labevents docs](https://mimic.mit.edu/docs/iv/modules/hosp/labevents) show `ref_range_lower`, `ref_range_upper` and a `flag` column, with out-of-range values abnormal, so per-row reference ranges ship with the data. Use the URL without a trailing slash (the slash form returned 404).
- [Synthea](https://github.com/synthetichealth/synthea): Apache-2.0, exports FHIR R4/STU3/DSTU2, bulk FHIR ndjson, C-CDA and CSV (CSV and bulk FHIR off by default). Its [observations.csv](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary) has LOINC CODE, DESCRIPTION, VALUE, UNITS and TYPE, with no reference range column. Earlier notes also list Synthea pre-generated FHIR zips and the Coherent set (CC BY 4.0, `s3://synthea-open-data/coherent/`).
- Sample PDFs: [JohnSnowLabs/pdf-deid-dataset](https://github.com/JohnSnowLabs/pdf-deid-dataset) is synthetic with Easy/Medium/Hard levels (about 50 PDFs; page counts are inconsistent) **(medium)**, includes a "Medical Tests" layout, and states no license (check the LICENSE file before reuse). No open dataset of lab-report PDFs with ground truth was found. Best approach: render MIMIC `labevents` or Synthea observations into PDFs with a template (reportlab or HTML-to-PDF), which gives exact ground truth.

**Reference ranges and criticals.** LOINC carries no ranges (earlier notes). MedlinePlus [potassium test page](https://medlineplus.gov/lab-tests/potassium-blood-test/) gives no numeric range, so it is not a loadable table. [MedlinePlus reuse policy](https://medlineplus.gov/about/using/usingcontent/): NLM-authored content is public domain with credit; A.D.A.M. encyclopedia and ASHP monographs are copyrighted and need a vendor license **(medium, corrected)**. A [2025 MLO article by Kost](https://www.mlo-online.com/diagnostics/article/55303948/table-of-critical-limits) compares 2024 critical-limit lists from 50 US hospitals with 1990-93 data from 92 medical centers, with tables as images **(medium)**; it does not confirm that limits vary by institution from the page text. Search snippets suggested differing institutional thresholds (for example potassium <2.8/>6.2 vs <3.0/>6.1) but these were not fetched, so hardcode a small illustrative table and label it as such.

**Entity extraction.** [Comprehend Medical DetectEntitiesV2](https://docs.aws.amazon.com/comprehend-medical/latest/dev/textanalysis-entitiesv2.html) finds TEST_NAME with TEST_VALUE and TEST_UNIT but has no reference-range attribute, so it cannot do the flagging itself. [Pricing](https://aws.amazon.com/comprehend/medical/pricing/) examples use $0.01 per 100-character unit; the page does not name DetectEntitiesV2.

**Incidental definition.** [Cleveland Clinic](https://my.clevelandclinic.org/health/diagnostics/incidental-finding): something found on a test that was not being looked for, often benign but occasionally serious (mostly discussed for imaging). A CSA Group article defining lab incidental findings surfaced in search but returned 403 and is not verified.

### Design suggestion (inference)
Have the model extract rows into a typed schema (name, value, unit, reference range from the PDF, source page), then apply a deterministic comparator for out-of-range and critical flags, and let the LLM only explain. Define "incidental" for labs as abnormal analytes unrelated to the stated reason for the visit.

### Recommended picks (labs)
1. MIMIC-IV demo `labevents` + `d_labitems`, rendered to PDF (ranges included, ODbL attribution needed).
2. Synthea observations as a second, license-clean (Apache-2.0) source; add your own range table.
3. JohnSnowLabs PDFs only for OCR robustness tests, pending license check.

### Gaps / unverified
- ARUP/Mayo/UChicago critical-value PDFs and Joint Commission NPSG.02.03.01 text were not fetched.
- LOINC license page returned 403 (registration need not verified).
- No verified MedlinePlus range table download.

---

## 5. Radiology Agent

**Models (open weights).**
| Model | License / access | Notes |
|---|---|---|
| [TorchXRayVision](https://github.com/mlmed/torchxrayvision) ([LICENSE](https://raw.githubusercontent.com/mlmed/torchxrayvision/master/LICENSE)) | Apache-2.0, pip install, no gating | DenseNet121 `densenet121-res224-all` gives 18 pathology scores (Nodule, Mass, Pneumothorax, Effusion, Cardiomegaly, Fracture, Hernia, Lung Lesion); CPU feasible |
| [MedGemma 4B IT](https://huggingface.co/google/medgemma-4b-it) | Gated; accept Health AI Developer Foundations terms on Hugging Face, approved immediately | Pre-trained on de-identified medical images incl. chest X-rays; card recommends Vertex AI, does not mention AWS, so AWS use means self-hosting; not for clinical use |
| [CheXagent-2-3b](https://huggingface.co/StanfordAIMI/CheXagent-2-3b) | MIT tag, ungated, `trust_remote_code=True` | Earlier notes called CheXagent research-only; the model card fetched today shows MIT, so re-read the card and its dataset terms before relying on it |
| [MAIRA-2](https://huggingface.co/microsoft/maira-2) | MSRLA, research only, gated | Poor fit for a demo implying clinical use |
| [LLaVA-Rad](https://huggingface.co/microsoft/llava-rad) | Research-only terms | Needs GPU |

**Hosting.** Self-hosted HF models can be deployed on a SageMaker GPU endpoint (for example ml.g5) and invoked through Converse using the endpoint ARN as modelId ([HF Bedrock quickstart](https://huggingface.co/docs/sagemaker/main/en/tutorials/bedrock/bedrock-quickstart)); GPU quota in a temporary account is a risk and no deploy time was verified. Bedrock-native alternatives accept images: [Claude Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.md) (launched 2026-09-28; ID `anthropic.claude-sonnet-5-5`, `us.`/`global.` profiles from us-east-1; supports Guardrails and structured outputs) and [Amazon Nova Pro](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-pro.md) (`amazon.nova-pro-v1:0`, no structured outputs). No source confirms X-ray interpretation quality on these or AWS policy for medical image use; check the Bedrock acceptable-use terms.

**Datasets.**
- [NIH ChestX-ray14, HF mirror](https://huggingface.co/datasets/alkzar90/NIH-Chest-X-ray-dataset): 112,120 frontal PNGs, 30,805 patients, 45.1 GB, 14 labels, no reports; card quotes NIH as imposing no restrictions beyond attribution; HF license metadata "unknown"; community mirror. Download only a small subset.
- [InRad COVID-19 CXR/CT](https://registry.opendata.aws/inlab-covid-19-images-dataset/): CC BY 4.0, bucket `inlab-opendata-covid-anonymized-images` in us-west-2, anonymous `--no-sign-request` access.
- Open-i / Indiana University (images with findings/impression reports): earlier notes cite it as non-commercial. The primary site showed a maintenance notice today, and a claim about the [ykumards/open-i HF mirror](https://huggingface.co/datasets/ykumards/open-i) (row count, columns, license) was **refuted** in verification; do not quote its specs. Check it yourself before use.
- [VinDr-CXR](https://physionet.org/content/vindr-cxr/1.0.0/): 18,000 studies but needs PhysioNet credentialing, CITI training and a DUA. Not usable today. MIMIC-CXR is also credentialed (earlier notes).
- Earlier notes also list the Synthea Coherent set (synthetic FHIR + DICOM, CC BY 4.0) as the only open multimodal per-patient set; useful if you want one linked patient.

**DICOM path.** [HealthImaging import](https://docs.aws.amazon.com/healthimaging/latest/devguide/importing-imaging-data.html) moves DICOM P10 files from S3 into a data store via import jobs; [overview](https://docs.aws.amazon.com/healthimaging/latest/devguide/what-is.html) states clinical use requires human review. For a one-day build, PNG/JPEG sent straight to Bedrock or TorchXRayVision avoids it.

**Incidental imaging findings.** [ACR Incidental Findings](https://www.acr.org/Clinical-Resources/Clinical-Tools-and-Reference/Incidental-Findings) lists committee white papers (full JACR text may be paywalled). The [Fleischner 2017 PubMed entry](https://pubmed.ncbi.nlm.nih.gov/28240562/) (not fully loaded; body did not render) concerns incidental nodules on CT, not chest X-ray, so a CXR-nodule follow-up (typically CT) must be encoded as your own labeled rule.

### Recommended picks (radiology)
1. TorchXRayVision for deterministic, auditable label scores (Apache-2.0, CPU) plus a Bedrock vision model (Sonnet 5.5) to write the narrative, with the scores passed as grounding.
2. NIH ChestX-ray14 subset (labels give you ground truth) and the InRad set for AWS-resident images.
3. MedGemma 4B only if a GPU endpoint is quickly available.

### Gaps / unverified
- No verified guideline for common incidental CXR findings beyond the TorchXRayVision label list.
- No source confirms MedGemma/CheXagent/MAIRA-2/LLaVA-Rad in JumpStart or Bedrock Marketplace.
- Official NIH download page license, RSNA/CheXpert/PadChest access flows, Open-i official figures.

---

## 6. Summarize node and incidental-finding flagging

- Merge Lab and Radiology outputs into one structured record (finding, source agent, evidence, confidence, severity, expected-vs-incidental tag), then emit two routes: wellness, and next steps (with the dashed incidental route).
- In Strands, fan-in needs care: Python Graph uses OR semantics by default, so give the aggregator an all-dependencies-complete edge condition to wait for both specialists ([Graph docs](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/graph/)).
- Guardrail pattern from earlier notes: separate critic/safety agent, deterministic escalation for red-flag values, human confirmation before care actions, and recording evidence and uncertainty. The documented failure mode is propagation of a planted false detail (50-82% hallucination across six LLMs, reduced with a mitigation prompt, per earlier notes).
- Definition of incidental (Section 4) is general; no lab-specific standard was verified, so state your operational definition in the demo.

### Recommended picks
1. Typed JSON schema for findings with an `incidental: bool` and `evidence` field; deterministic severity rules.
2. A critic pass that re-checks each flagged item against the source extraction.
3. Always show "not medical advice" plus a clinician-review banner.

### Gaps / unverified
- No peer-reviewed open benchmark for lab incidental-finding detection was found.

---

## 7. Wellness Agent (nutrition, physio, OTC while waiting)

**Sources.**
- OTC labels: [openFDA drug label API](https://open.fda.gov/apis/drug/label/) returns Rx and OTC labels (JSON). Limits: 240 requests/min per IP, 1,000/day without a key, 120,000/day with a free key; the page also says a key is "required", which is inconsistent with the unkeyed limits it lists **(medium)** ([auth](https://open.fda.gov/apis/authentication/)). [FAERS endpoint](https://open.fda.gov/apis/drug/event/) states it cannot establish causality and should not be the sole basis for clinical decisions. [DailyMed services](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm): GET only, XML/JSON, endpoints under `/dailymed/services/v2/` (base-URI wording **medium**).
- Nutrition: [USDA FoodData Central API](http://fdc.nal.usda.gov/api-guide/) (data.gov key, 1,000 req/hr/IP, DEMO_KEY 30/hr and 50/day, CC0 data). [NHLBI DASH](https://www.nhlbi.nih.gov/education/dash-eating-plan): 2,300 mg sodium/day, 1,500 mg for greater BP lowering, on a 2,000-calorie diet.
- Physio: [CDC adult activity guidelines](https://www.cdc.gov/physical-activity-basics/guidelines/adults.html): 150 min/week moderate (or 75 vigorous) plus strengthening on 2+ days. [OrthoInfo low back pain](https://www.orthoinfo.org/en/diseases--conditions/low-back-pain/) lists acetaminophen and NSAIDs (aspirin, ibuprofen, naproxen) and advises seeing a doctor if no improvement in a few weeks (AAOS copyright: link, do not copy). [wger](https://github.com/wger-project/wger) ([API docs](https://wger.readthedocs.io/en/latest/api/api.html)): public exercise list needs no auth, 20 per page; code AGPL-3.0+, exercise data CC per entry.
- Prior art: [otc-safe-dose](https://github.com/Mehar-Ali1122/otc-safe-dose) (MIT; "The LLM never chooses a drug or a dose"; deterministic rules plus independent validator) and [FDA-Label-Agent](https://github.com/sruthimundekkottil/FDA-Label-Agent) (MIT; LangGraph over openFDA labels; not a medical device).

**Safety design (inference).** Make OTC output a label-grounded options list with "do not use if" conditions pulled from openFDA, deterministic exclusion for kidney, liver, pregnancy and anticoagulant flags, and a "talk to a pharmacist" line. The earlier RxNav interaction API appeared discontinued in a search snippet (about 2024-01-02; not verified), so rely on label `drug_interactions`/`do_not_use` fields plus a small hand-built contraindication table.

### Recommended picks
1. openFDA label API (with free key) as the single OTC source, rules-first as in otc-safe-dose.
2. USDA FoodData Central + DASH for budget nutrition (cite sodium targets).
3. CDC activity guidance plus a hardcoded, cited physio set (wger as optional exercise lookup, mind AGPL).

### Gaps / unverified
- NIH ODS fact sheets, FDA OTC monograph M013 (PDF not parsed), USDA Thrifty Food Plan and MyPlate pages were unreachable.
- No verified NSAID + CKD contraindication source.
- No validated "wellness while waiting" project found, only prototypes.

---

## 8. Insurance Agent

- The card yields member ID, group, payer ID, plan name, Rx BIN/PCN/GRP and copays (fields Mindee returns; Section 3).
- Payer IDs: [Waystar payer list](https://login.zirmed.com/ui/Payers) has a Download (.CSV) link and class filters (login requirement not stated); [Office Ally list](https://cms.officeally.com/payerlist) showed a maintenance notice; a [third-party list](https://medicalbillingrcm.com/insurance-payer-id-list-medical-billing/) shows UnitedHealthcare 87726, Aetna 60054, Cigna 62308, some entries "Call" (unofficial, mixed dates). No official CMS or NAIC list was found.
- Network membership requires payer data. [Da Vinci PDEX Plan-Net v1.2.0](https://hl7.org/fhir/us/davinci-pdex-plan-net/) defines a read-only FHIR R4 directory of plans, networks, organizations and practitioners. Verified open endpoints: [UnitedHealthcare](https://www.uhc.com/legal/interoperability-apis/patient-access-api) (`https://flex.optum.com/fhirpublic/R4/`, no registration), [CHRISTUS Health Plan](https://www.christushealthplan.org/privacy-and-patient-rights/interoperability/provider-directory-api) (Texas, `https://doctors.christushealthplan.org/fhir/provider-directory`), [Peak Health Medicare](https://medicare.peakhealth.org/interoperability/). Aetna, BCBS Texas, Humana and Centene open directories were not verified.
- Price-transparency files: [CMSgov/price-transparency-guide](https://github.com/CMSgov/price-transparency-guide) schemas and [Centene files](https://www.centene.com/price-transparency-files.html) (JSON, monthly, very large); too heavy for one day.
- Neither the NPI Registry nor the CMS clinician file lists accepted plans (Section 9).

### Recommended picks
1. Use a synthetic plan with a small hand-built in-network roster, backed by a live Plan-Net query to UnitedHealthcare or CHRISTUS for credibility.
2. Normalize the card to a payer ID via a small lookup table (seed from the Waystar CSV if it downloads).
3. Skip price-transparency files.

### Gaps / unverified
- Waystar and Office Ally download formats and login needs; live behavior of the Plan-Net endpoints for searching by specialty was not exercised beyond metadata statements.

---

## 9. Scheduling Agent

- Find specialists: [NPPES NPI Registry API v2.1](https://npiregistry.cms.hhs.gov/api/?version=2.1&taxonomy_description=Cardiovascular%20Disease&city=Austin&state=TX&limit=3) works unauthenticated; a live query for cardiologists in Austin, TX returned 3 results with taxonomy 207RC0000X on 2026-10-23. Per the rOpenSci [npi vignette](https://docs.ropensci.org/npi/articles/npi.html) (secondary): up to 200 records per request, 1,200 per unique query, no documented rate limit. The official docs page is JS-rendered and unread.
- [CMS Doctors and Clinicians National Downloadable File](https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/mj5m-pzi6): one row per clinician/enrollment/group/address, modified 2026-10-02, public CSV; license not stated.
- Taxonomy: [NUCC code set](https://www.nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40) downloadable as CSV/PDF; commercial products embedding it must request a license. Codes 207RC0000X, 207RP1001X, 207RE0101X were confirmed only on third-party sites and orthopaedic surgery 207X00000X was not confirmed; verify at taxonomy.nucc.org.
- Booking sandbox: [HAPI FHIR R4 public server](https://hapi.fhir.org/baseR4/metadata?_summary=true) (FHIR 4.0.1, Appointment present, 447 at fetch time) serves [Slot](https://hapi.fhir.org/baseR4/Slot?_count=1) without auth. [FHIR R4 Appointment](https://www.hl7.org/fhir/R4/appointment.html): statuses include proposed, pending, booked, waitlist, cancelled; it books Slots from a Schedule. Use `proposed` for the "propose follow-up appointments" step and keep human confirmation. HAPI is a shared public test server: never write real or personal data. [Epic on FHIR](https://fhir.epic.com/) needs developer sign-up and client registration (too slow); Slot/Schedule reads are STU3 only.
- Collaboration with Insurance: no verified doc example of bidirectional Insurance <-> Scheduling exists. Implement as one Next Steps orchestrator that calls an Insurance tool (network check) and a Scheduling tool in a loop (propose, check network, re-propose).

### Recommended picks
1. NPI Registry query by taxonomy + city to build candidate lists, intersect with the Insurance Agent's in-network roster.
2. Create `proposed` Appointment resources against HAPI FHIR (or a local mock) for the demo.
3. Map findings to specialties through a small hand-authored table (for example nodule to pulmonology, abnormal potassium to nephrology or primary care), labeled as a prototype rule set.

### Gaps / unverified
- SMART launcher and CMS interoperability rule deadlines unread; the Provider Data Catalog datastore query endpoint pattern is third-party only.

---

## 10. Orchestration on AWS

- Pattern choice ([multi-agent patterns](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/multi-agent-patterns/)): Graph for a developer-defined flowchart, Swarm for emergent handoffs, Workflow for a fixed DAG with parallel tasks and no cycles. Your diagram is a fan-out/fan-in DAG, so Graph (supports the parallel specialists) with Next Steps as an agents-as-tools sub-orchestrator for the Insurance/Scheduling loop. That last choice is an inference; Graph cycles are mentioned by the pattern guide but a Swarm or sub-orchestrator for Next Steps was not confirmed.
- Multimodal Graph input is a list of ContentBlocks (text plus `image` with bytes) ([Graph docs](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/graph/)).
- Streaming for a "visible handoff" UI: Python `Graph.stream_async` emits `multiagent_node_start`, `multiagent_node_stream`, `multiagent_node_stop` and `multiagent_result`; forward them as SSE. The AgentCore Runtime [HTTP contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html): container on 0.0.0.0:8080, ARM64, `POST /invocations` returns JSON or SSE, `/ping` health.
- Deploy: [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html): `agentcore create --template agent-python-strands`, then `dev`, `build`, `deploy`, `invoke`; the template provisions AgentCore Memory. [Memory overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html): short-term session and long-term cross-session memory (API names unverified).
- Tools via [AgentCore Gateway OpenAPI targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html): OpenAPI 3.0/3.1 **(medium; intro text says only 3.0)**, `operationId` becomes the MCP tool name, no oneOf/anyOf/allOf, outbound auth none/OAuth/API key/IAM SigV4 (SigV4 only for targets behind AWS services that verify it **(medium)**). Simpler for one day: plain `@tool` Python functions calling NPI, openFDA and FHIR directly (inference).
- Models: [Bedrock model catalog](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-supported-models-features.html) (as of Oct 2026) lists Claude 4.5/5.x, Nova 2 Lite/Pro/Lite, GPT-5.x/6 variants and Qwen3 VL. Sonnet 5.5 is reachable from us-east-1 via `global.anthropic.claude-sonnet-5-5` or `us.anthropic.claude-sonnet-5-5`; a model access/marketplace enablement step may be needed. Confirm in the Workshop Studio account which models are enabled before building.
- Repos to fork: [strands-agents/samples](https://github.com/strands-agents/samples) (Apache-2.0; 01-learn multi-agent, 02-deploy AgentCore, 04-industry-use-cases healthcare, 07-ux-demos). A verification attempt on [aws-samples/sample-medical-content-review-agent](https://github.com/aws-samples/sample-medical-content-review-agent) **refuted** the specific claim about its architecture and folder layout; treat that description as unverified and open the repo before copying structure. Earlier notes list additional AWS healthcare samples (`aws-samples/amazon-bedrock-agents-healthcare-lifesciences`, `healthcare-appointment-agent`, `sample-multiagent-multimodal-hcls`), MIT-0 licensed, and note that Bedrock Agents Classic is closed to new customers since 2026-07-30, so use AgentCore + Strands, not Bedrock Agents.
- Guardrails/PHI: see Section 3; add audit logging of tool calls and evidence per the track guardrails.

### Recommended picks
1. Strands Graph (parallel Lab and Radiology, all-complete fan-in) wrapped for AgentCore Runtime, with SSE to a simple UI.
2. Plain Python tools first, Gateway only if time permits.
3. A fixed model ID verified in the account on morning of the build, with a cheaper fallback (Nova or Haiku 4.5, per the catalog).

### Gaps / unverified
- Parallel `asyncio.gather` invocation and agents-as-tools async pattern not verified against docs.
- Python Graph handoff event equivalent to TypeScript `multiAgentHandoffEvent` not documented.
- Whether a temporary Workshop Studio account permits AgentCore Runtime deployment and SageMaker GPU quota.

---

## 11. Pitfalls found during verification

- Refuted: ykumards/open-i HF mirror specs (do not quote); aws-samples/sample-medical-content-review-agent architecture claim.
- Corrected: JohnSnowLabs PDF counts, MedlinePlus licensing split, Kost article scope, DailyMed base URI, Gateway OpenAPI details, openFDA "key required" wording.
- URL quirks: MIMIC `labevents` docs 404 with trailing slash; Synthea downloads page failed certificate verification; several federal and publisher pages (RxNav, NIH ODS, RSNA, JACR, CSA) returned 403.
- Mismatch to resolve: CheXagent license (research-only in earlier notes vs MIT tag on the fetched card).

## 12. Suggested one-day build order

1. Fix the demo patient: a MIMIC/Synthea lab set rendered to PDF, one NIH CXR with a known label, one synthetic insurance card.
2. Lab and Radiology agents with deterministic flags, run in parallel in a Strands Graph.
3. Summarize node with the incidental tag and critic pass.
4. Next Steps: NPI search, synthetic network roster, `proposed` Appointment.
5. Wellness agent with openFDA-grounded OTC rules.
6. Deploy via AgentCore CLI, SSE handoff UI, disclaimers.
