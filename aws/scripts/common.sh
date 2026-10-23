#!/usr/bin/env bash
# Shared settings for the deploy scripts. Override any of these in the environment.
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
export STACK_NAME="${STACK_NAME:-carerelay}"
export ECR_LAMBDA_REPO="${ECR_LAMBDA_REPO:-carerelay-lambda}"
export ECR_AGENTCORE_REPO="${ECR_AGENTCORE_REPO:-carerelay-agentcore}"
export IMAGE_TAG="${IMAGE_TAG:-$(git -C "$(dirname "$0")/../.." rev-parse --short HEAD 2>/dev/null || echo latest)}"
export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-4-5-20250929-v1:0}"
export AGENT_RUNTIME_NAME="${AGENT_RUNTIME_NAME:-carerelay_careteam}"

export ECR_HOST="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
export LAMBDA_IMAGE_URI="${ECR_HOST}/${ECR_LAMBDA_REPO}:${IMAGE_TAG}"
export AGENTCORE_IMAGE_URI="${ECR_HOST}/${ECR_AGENTCORE_REPO}:${IMAGE_TAG}"
export REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

stack_output() {  # stack_output OutputKey
  aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
