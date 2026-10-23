#!/usr/bin/env bash
# Lane A: deploy the CloudFormation/SAM stack (Lambda + Function URL + S3 + IAM + AgentCore role).
# Works without the SAM CLI: CloudFormation applies the Serverless transform itself.
source "$(dirname "$0")/common.sh"

aws cloudformation deploy --region "$AWS_REGION" --stack-name "$STACK_NAME" \
  --template-file "$REPO_ROOT/aws/template.yaml" \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    "LambdaImageUri=$LAMBDA_IMAGE_URI" \
    "BedrockModelId=$BEDROCK_MODEL_ID" \
    "FunctionUrlAuthType=${FUNCTION_URL_AUTH:-NONE}" \
  --tags Project=CareRelay Event=atx-agentic-ai-hackathon

echo "FunctionUrl:              $(stack_output FunctionUrl)"
echo "ReportBucketName:         $(stack_output ReportBucketName)"
echo "AgentCoreExecutionRoleArn: $(stack_output AgentCoreExecutionRoleArn)"
