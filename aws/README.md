# aws/

Deployment lanes for CareRelay. Every lane calls `carerelay.service.handle(request)`; they differ only in entry point and where the report lands. Full write-up with the diagrams: [docs/AWS_INFRASTRUCTURE.md](../docs/AWS_INFRASTRUCTURE.md).

| Path | Lane | What it is |
|---|---|---|
| `template.yaml` | A (+ role for B) | SAM/CloudFormation: Lambda container image, Function URL, private S3 report bucket with 14-day expiry, IAM, log retention, AgentCore execution role |
| `lambda/` | A | `Dockerfile` (arm64, `public.ecr.aws/lambda/python:3.12`) and `handler.py` (Function URL event -> `service.handle` -> S3 + presigned links) |
| `agentcore/` | B | `Dockerfile` (linux/arm64) and `app.py` (`BedrockAgentCoreApp`, `POST /invocations`, `GET /ping` on 8080) |
| `streamlit/` | C | `portal.py`: patient-portal demo, drag PDFs in, stages light up live, report tabs (the one to show judges, see [docs/DEMO.md](../docs/DEMO.md)); `app.py`: minimal scenario picker |
| `iam-bedrock-policy.json` | all | Bedrock inference + Comprehend Medical permissions every lane's role needs |
| `scripts/` | all | `build_push.sh`, `deploy_lambda.sh`, `deploy_agentcore.sh`, `invoke.sh`, `cleanup.sh` |
| `Makefile` | all | `make -C aws help` |

Quick path on hackathon day:

```bash
export AWS_REGION=us-east-1 BEDROCK_MODEL_ID=<allow-listed profile>
make -C aws validate
make -C aws invoke-local            # pipeline runs locally, no AWS
make -C aws portal                  # Lane C, the patient-portal demo (drag PDFs in)
make -C aws streamlit               # Lane C, minimal scenario picker
make -C aws push deploy-lambda      # Lane A: judges get a URL
make -C aws deploy-agentcore        # Lane B: agent hosted on AgentCore
make -C aws clean                   # before leaving
```
