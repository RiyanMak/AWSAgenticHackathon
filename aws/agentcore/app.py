"""Lane B: Bedrock AgentCore Runtime entrypoint.

The runtime contract: an arm64 container listening on 0.0.0.0:8080 with POST /invocations and
GET /ping. ``BedrockAgentCoreApp`` provides both; the decorated function receives the JSON payload.

    aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn ... \
        --payload '{"prompt": "run case_001"}' out.json
    aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn ... \
        --payload '{"scenario": "case_005", "options": {"llm": true}}' out.json
"""

from __future__ import annotations

import logging
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from carerelay import service

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("carerelay.agentcore")

app = BedrockAgentCoreApp()


def _to_request(payload: Any) -> dict[str, Any] | str:
    """Accept {"prompt": "..."} (free text), a full request dict, or a bare string."""
    if isinstance(payload, dict):
        if "prompt" in payload and not ({"scenario", "inputs"} & set(payload)):
            return str(payload["prompt"])
        return payload
    return str(payload)


@app.entrypoint
def invoke(payload: Any, context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    try:
        report = service.handle(_to_request(payload))
    except service.ServiceError as exc:
        return {"error": str(exc), "scenarios": [s["case_id"] for s in service.list_scenarios()]}
    log.info("case=%s elapsed=%ss", report.get("case_id"), report["elapsed_seconds"])
    return report


if __name__ == "__main__":
    app.run()
