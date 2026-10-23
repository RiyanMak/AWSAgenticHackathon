#!/usr/bin/env bash
# Lane B: create or update the AgentCore Runtime from the pushed arm64 image.
# Needs the stack from deploy_lambda.sh for the execution role (or set AGENTCORE_ROLE_ARN).
source "$(dirname "$0")/common.sh"

ROLE_ARN="${AGENTCORE_ROLE_ARN:-$(stack_output AgentCoreExecutionRoleArn)}"
existing=$(aws bedrock-agentcore-control list-agent-runtimes --region "$AWS_REGION" \
  --query "agentRuntimes[?agentRuntimeName=='$AGENT_RUNTIME_NAME'].agentRuntimeId" --output text 2>/dev/null || true)

if [[ -z "$existing" || "$existing" == "None" ]]; then
  echo "creating runtime $AGENT_RUNTIME_NAME from $AGENTCORE_IMAGE_URI"
  out=$(aws bedrock-agentcore-control create-agent-runtime --region "$AWS_REGION" \
    --agent-runtime-name "$AGENT_RUNTIME_NAME" \
    --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"$AGENTCORE_IMAGE_URI\"}}" \
    --role-arn "$ROLE_ARN" \
    --network-configuration '{"networkMode":"PUBLIC"}' \
    --environment-variables "{\"BEDROCK_MODEL_ID\":\"$BEDROCK_MODEL_ID\",\"AWS_REGION\":\"$AWS_REGION\"}" \
    --description "CareRelay care-team pipeline (service.handle)")
else
  echo "updating runtime $existing with $AGENTCORE_IMAGE_URI"
  out=$(aws bedrock-agentcore-control update-agent-runtime --region "$AWS_REGION" \
    --agent-runtime-id "$existing" \
    --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"$AGENTCORE_IMAGE_URI\"}}" \
    --role-arn "$ROLE_ARN" \
    --network-configuration '{"networkMode":"PUBLIC"}' \
    --environment-variables "{\"BEDROCK_MODEL_ID\":\"$BEDROCK_MODEL_ID\",\"AWS_REGION\":\"$AWS_REGION\"}")
fi
echo "$out"
echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("AGENT_RUNTIME_ARN=" + d.get("agentRuntimeArn",""))'
