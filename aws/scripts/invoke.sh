#!/usr/bin/env bash
# Smoke-test a lane. Usage:
#   aws/scripts/invoke.sh lambda [case_001]
#   aws/scripts/invoke.sh agentcore <agent-runtime-arn> [case_001]
#   aws/scripts/invoke.sh local [case_001]            # service.handle in-process, no AWS
source "$(dirname "$0")/common.sh"
lane="${1:-local}"

case "$lane" in
  lambda)
    url="$(stack_output FunctionUrl)"
    curl -s "${url}?scenario=${2:-case_001}" | python3 -m json.tool | head -60
    ;;
  agentcore)
    arn="$2"; scenario="${3:-case_001}"
    aws bedrock-agentcore invoke-agent-runtime --region "$AWS_REGION" --agent-runtime-arn "$arn" \
      --payload "{\"scenario\":\"$scenario\"}" /dev/stdout | python3 -m json.tool | head -60
    ;;
  local)
    cd "$REPO_ROOT" && .venv/bin/python -c "
import json, sys
from carerelay import service
r = service.handle({'scenario': '${2:-case_001}', 'options': {'llm': False}})
print(json.dumps({k: v['status'] for k, v in r['stages'].items()})); print(r['report']['markdown'][:1200])"
    ;;
  *) echo "unknown lane $lane"; exit 1 ;;
esac
