# AWS Setup

Event: AWS Austin Agentic AI Hackathon, 2026-10-23, Track 1, Workshop Studio temporary account, us-east-1. Back to [README](../README.md).

## 1. Join Workshop Studio

1. Open a fresh or private browser window and the [join page](https://catalog.us-east-1.prod.workshops.aws/join?access-code=a52a-010f17-28). The 12-digit access code is `a52a-010f17-28`; the track page still says to get it from the event operator, so it may change.
2. Sign in (email one-time password, Login with Amazon, or Amazon employee), enter the code, accept the terms, and open AWS account access.
3. Verify in the console that you are `WSParticipantRole` in us-east-1.
4. Open the [Event dashboard](https://catalog.us-east-1.prod.workshops.aws/event/dashboard/en-US), then `Event outputs`:
   - `VScodeIdeURL` opens browser VS Code on the shared `/workshop` folder (recommended).
   - `KiroRDPConnectionURL` opens Kiro on Ubuntu Desktop; credentials are in `KiroRDPCredentials`. Do not copy them into notes or chat.
5. Optional CLI credentials from Workshop Studio expire after 60 minutes; copy a fresh set when needed.

## 2. Starter kit commands

```bash
curl -fsSL https://atx.rahman.dev/hackathon-kit.zip -o hackathon-kit.zip && unzip -qo hackathon-kit.zip
export AWS_REGION=us-east-1
aws sts get-caller-identity
python3 --version
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python infer.py            # expect "OK" or "OK."
.venv/bin/python setup_agentcore_role.py
agentcore configure --entrypoint agent.py --name workshop_gpt_agent --region "$AWS_REGION" \
  --deployment-type direct_code_deploy --requirements-file requirements.txt \
  --execution-role "$AGENTCORE_EXECUTION_ROLE_ARN" --disable-otel --disable-memory --non-interactive
agentcore deploy --agent workshop_gpt_agent --env "BEDROCK_MODEL_ID=$BEDROCK_MODEL_ID"
agentcore invoke '{"prompt":"Reply with OK."}' --agent workshop_gpt_agent
```

The kit installs `boto3`, `bedrock-agentcore` and `bedrock-agentcore-starter-toolkit`. Keep the working baseline, then replace the handler in `agent.py` with the Strands Graph. Do not put credentials in `agent.py`. If another participant shares your account, set a unique `AGENTCORE_ROLE_NAME` before running the role script.

For a Strands-based scaffold the report suggests `agentcore create --template agent-python-strands`, then `dev`, `build`, `deploy`, `invoke`; the template provisions AgentCore Memory.

## 3. Model allowlist check

The kit default is `us.openai.gpt-5.6-luna`; tested alternatives are `us.openai.gpt-5.4`, `us.openai.gpt-5.5`, `us.openai.gpt-5.6-sol` and `us.openai.gpt-5.6-terra`. The report recommends Claude Sonnet 5.5 (`us.anthropic.claude-sonnet-5-5` or `global.anthropic.claude-sonnet-5-5`) for vision, but whether it is enabled in the workshop account is not known. Check on the morning of the build:

```bash
aws bedrock list-inference-profiles --region "$AWS_REGION" --query "inferenceProfileSummaries[].inferenceProfileId"
aws bedrock-runtime converse --region "$AWS_REGION" --model-id us.anthropic.claude-sonnet-5-5 \
  --messages '[{"role":"user","content":[{"text":"Reply OK"}]}]'
```

Verified on 2026-10-23 on a personal account in us-east-1 and us-west-2: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, `us.anthropic.claude-haiku-4-5-20251001-v1:0` and `us.amazon.nova-2-lite-v1:0` invoke; `us.anthropic.claude-sonnet-5` and `us.anthropic.claude-opus-5-5` are listed but return `AccessDeniedException` until model access is granted. The History Agent defaults to Sonnet 4.5 and reads `BEDROCK_MODEL_ID` to override.

Fallbacks: a kit-tested GPT profile, `amazon.nova-pro-v1:0` (supports images, no structured outputs), or Haiku 4.5 per the Bedrock catalog. Test PDF support per model; if a model has no document row, render PDF pages to images. A Bedrock API key does not override an IAM explicit deny.

## 4. IAM caveats

- The role script needs `iam:CreateRole`, `iam:PutRolePolicy` and `iam:PassRole`; otherwise `AccessDenied` and the script cannot grant itself permissions.
- AgentCore Runtime deploy needs permission to create and invoke runtimes and to use an S3 code bucket.
- Direct inference and AgentCore inference use different roles. If one works and the other fails, compare roles and the allowlist.
- It is unknown whether the temporary account permits AgentCore Runtime deployment or SageMaker GPU quota. Test early; fall back to running the graph locally.
- Comprehend Medical needs `comprehendmedical:InferICD10CM` and `comprehendmedical:InferRxNorm` (the managed policy `ComprehendMedicalFullAccess` covers both). Without them the intake parser keeps items as uncoded text and records a warning; it does not fail.

## 5. Services used

| Service | Purpose | Notes |
|---|---|---|
| Amazon Bedrock (Converse) | Multimodal reading of PDF, X-ray, card; agent reasoning | Image input via ImageBlock; PDF via DocumentBlock (prompt-injection warning) |
| AgentCore Runtime | Hosts the Strands Graph | Container on 0.0.0.0:8080, ARM64, `POST /invocations` JSON or SSE, `/ping` |
| AgentCore Gateway | Optional OpenAPI-to-MCP tools | Plain `@tool` functions first |
| AgentCore Memory | Session context | Provisioned by the Strands template; API names unverified |
| Textract (TABLES) | Fallback for dense lab grids | Sync PDF max 1 page and 10 MB |
| Bedrock Data Automation | Optional document/image extraction | Availability in the account unverified |
| Comprehend Medical | DetectPHI scrub, DetectEntitiesV2 for TEST_NAME/VALUE/UNIT, InferICD10CM and InferRxNorm for the free-text medical history intake | No reference-range attribute; structured FHIR or CSV history is parsed without it |
| Bedrock Guardrails | Sensitive-information filters, content policy | Not applied to tool-call arguments or results |
| S3, CloudWatch | Uploads (encrypted), audit logs | Encryption at rest and in transit per track guardrail |
| HealthImaging (optional) | DICOM import from S3 | Skip for one day; PNG/JPEG goes straight to Bedrock |

Do not use Bedrock Agents Classic (closed to new customers since 2026-07-30); use AgentCore plus Strands.

## 6. Pricing notes

Oregon rates shown; us-east-1 not listed on the pages. Negligible at demo volume.

| Item | Rate |
|---|---|
| Textract Detect Text / Tables / Forms / Queries | $0.0015 / $0.015 / $0.05 / $0.015 per page |
| Bedrock Data Automation | Standard $0.010/page; custom $0.040/page (30 or fewer fields); $0.005/image |
| Comprehend Medical | Examples use $0.01 per 100-character unit |
| AgentCore Runtime | $0.0895/vCPU-hr and $0.00945/GB-hr (microVM v1), billed per second |
| AgentCore Gateway | $0.005 per 1,000 API invocations |

Sources: [Textract pricing](https://aws.amazon.com/textract/pricing/), [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/), [Comprehend Medical pricing](https://aws.amazon.com/comprehend/medical/pricing/), [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).

## 7. Cleanup

Each inference and active AgentCore runtime can incur charges. When finished:

1. Delete the runtime (`workshop_gpt_agent` or ours) via the AgentCore CLI or console.
2. Delete the dedicated role (`hackathon-gpt-agentcore-execution-role` or your `AGENTCORE_ROLE_NAME`).
3. Empty and delete any S3 buckets you created, and delete any SageMaker endpoints or Positron domain.
4. Follow the event's own cleanup procedure.

See also: [ARCHITECTURE.md](ARCHITECTURE.md), [TODO.md](TODO.md).
