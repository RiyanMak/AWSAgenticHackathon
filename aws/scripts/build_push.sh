#!/usr/bin/env bash
# Build both container images (arm64) and push them to ECR. Usage: aws/scripts/build_push.sh [lambda|agentcore|all]
source "$(dirname "$0")/common.sh"
target="${1:-all}"

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_HOST"

ensure_repo() {
  aws ecr describe-repositories --region "$AWS_REGION" --repository-names "$1" >/dev/null 2>&1 \
    || aws ecr create-repository --region "$AWS_REGION" --repository-name "$1" \
         --image-scanning-configuration scanOnPush=true --encryption-configuration encryptionType=AES256 >/dev/null
}

if [[ "$target" == "lambda" || "$target" == "all" ]]; then
  ensure_repo "$ECR_LAMBDA_REPO"
  docker buildx build --platform linux/arm64 -f "$REPO_ROOT/aws/lambda/Dockerfile" \
    -t "$LAMBDA_IMAGE_URI" --provenance=false --push "$REPO_ROOT"
  echo "LAMBDA_IMAGE_URI=$LAMBDA_IMAGE_URI"
fi

if [[ "$target" == "agentcore" || "$target" == "all" ]]; then
  ensure_repo "$ECR_AGENTCORE_REPO"
  docker buildx build --platform linux/arm64 -f "$REPO_ROOT/aws/agentcore/Dockerfile" \
    -t "$AGENTCORE_IMAGE_URI" --provenance=false --push "$REPO_ROOT"
  echo "AGENTCORE_IMAGE_URI=$AGENTCORE_IMAGE_URI"
fi
