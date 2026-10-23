# External APIs

All calls are read-only except HAPI FHIR Appointment creation (public sandbox, synthetic data only). Send no patient identifiers to any of them. Back to [README](../README.md).

Set these once in your shell before running the examples:

```bash
export OPENFDA_BASE=https://api.fda.gov
export FDC_BASE=https://api.nal.usda.gov/fdc/v1
export WGER_BASE=https://wger.de/api/v2
export HAPI_BASE=https://hapi.fhir.org/baseR4
export UHC_BASE=https://flex.optum.com/fhirpublic/R4
export CHRISTUS_BASE=https://doctors.christushealthplan.org/fhir/provider-directory
```

| API | Base URL / docs | Auth | Rate limit | Used by |
|---|---|---|---|---|
| NPI Registry (NPPES) v2.1 | `https://npiregistry.cms.hhs.gov/api/` | None | No documented limit; up to 200 records per request, 1,200 per unique query (secondary source) | Scheduling |
| CMS Doctors and Clinicians file | [dataset item](https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/mj5m-pzi6) | None (public CSV) | Not stated | Scheduling (optional) |
| Payer FHIR directories (Plan-Net) | `https://flex.optum.com/fhirpublic/R4/` (UnitedHealthcare), `https://doctors.christushealthplan.org/fhir/provider-directory` (CHRISTUS, Texas) | None | Not stated | Insurance |
| HAPI FHIR R4 sandbox | `https://hapi.fhir.org/baseR4` | None | Shared public server | Scheduling |
| openFDA drug label | [docs](https://open.fda.gov/apis/drug/label/) | Free key ([auth](https://open.fda.gov/apis/authentication/)) | 240/min per IP; 1,000/day without key, 120,000/day with key (**medium**: page also says key "required") | Wellness |
| openFDA FAERS | [docs](https://open.fda.gov/apis/drug/event/) | Same | Same | Not used for advice (cannot establish causality) |
| DailyMed web services | [docs](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm) | None | Not stated | Wellness (label text cross-check; base URI wording **medium**) |
| USDA FoodData Central | [API guide](http://fdc.nal.usda.gov/api-guide/) | data.gov key | 1,000/hr per IP; `DEMO_KEY` 30/hr and 50/day | Wellness |
| wger exercises | [API docs](https://wger.readthedocs.io/en/latest/api/api.html) | None for public exercise list | 20 per page | Wellness (optional) |
| RxNorm / RxNav | Not verified | n/a | The RxNav interaction API appeared discontinued (about 2024-01-02, unverified) | Not used; rely on label fields plus a hand-built contraindication table |

## Example requests

NPI Registry, cardiologists in Austin (verified live on 2026-10-23, returned 3 results):

```bash
curl -s "https://npiregistry.cms.hhs.gov/api/?version=2.1&taxonomy_description=Cardiovascular%20Disease&city=Austin&state=TX&limit=3"
```

Plan-Net metadata (UnitedHealthcare) and a practitioner search by name (adjust search params per the Plan-Net spec):

```bash
curl -s "$UHC_BASE/metadata"
curl -s "$CHRISTUS_BASE/metadata"
```

HAPI FHIR: read slots, then propose an appointment (synthetic data only):

```bash
curl -s "$HAPI_BASE/Slot?_count=1"
curl -s -X POST "$HAPI_BASE/Appointment" \
  -H "Content-Type: application/fhir+json" \
  -d '{"resourceType":"Appointment","status":"proposed","description":"Synthetic demo follow-up",
       "participant":[{"status":"needs-action"}]}'
```

Use status `proposed` and keep human confirmation before `booked`.

openFDA label search (OTC pain relievers; add `&api_key=$OPENFDA_KEY` if you have a key):

```bash
curl -s "$OPENFDA_BASE/drug/label.json?search=openfda.generic_name:ibuprofen&limit=1"
```

Read `do_not_use`, `drug_interactions`, `warnings` and `dosage_and_administration` from the result; the model never chooses a drug or dose.

USDA FoodData Central food search:

```bash
curl -s "$FDC_BASE/foods/search?query=canned%20beans&pageSize=3&api_key=$FDC_KEY"
```

wger public exercise list (no auth, 20 per page):

```bash
curl -s "$WGER_BASE/exercise/?limit=20"
```

Note: wger code is AGPL-3.0+, so call it as a service and do not copy code.

## Tool wrappers

Start with plain `@tool` Python functions calling these APIs directly. AgentCore Gateway OpenAPI targets are optional (OpenAPI 3.0/3.1, `operationId` becomes the MCP tool name, no oneOf/anyOf/allOf). See [AWS_SETUP.md](AWS_SETUP.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
