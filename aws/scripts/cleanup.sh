#!/usr/bin/env bash
# Tear everything down (track guardrail: leave no runtimes or buckets behind). Usage: aws/scripts/cleanup.sh
source "$(dirname "$0")/common.sh"

rt=$(aws bedrock-agentcore-control list-agent-runtimes --region "$AWS_REGION" \
  --query "agentRuntimes[?agentRuntimeName=='$AGENT_RUNTIME_NAME'].agentRuntimeId" --output text 2>/dev/null || true)
if [[ -n "$rt" && "$rt" != "None" ]]; then
  echo "deleting agent runtime $rt"; aws bedrock-agentcore-control delete-agent-runtime --region "$AWS_REGION" --agent-runtime-id "$rt"
fi

bucket=$(stack_output ReportBucketName 2>/dev/null || true)
if [[ -n "$bucket" && "$bucket" != "None" ]]; then
  echo "emptying s3://$bucket"; aws s3 rm "s3://$bucket" --recursive --region "$AWS_REGION" >/dev/null || true
fi

echo "deleting stack $STACK_NAME"
aws cloudformation delete-stack --region "$AWS_REGION" --stack-name "$STACK_NAME"
aws cloudformation wait stack-delete-complete --region "$AWS_REGION" --stack-name "$STACK_NAME" || true

for repo in "$ECR_LAMBDA_REPO" "$ECR_AGENTCORE_REPO"; do
  aws ecr delete-repository --region "$AWS_REGION" --repository-name "$repo" --force >/dev/null 2>&1 && echo "deleted ECR $repo" || true
done
echo "done"
