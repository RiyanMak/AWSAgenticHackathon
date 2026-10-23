"""Lane A: Lambda container image behind a Function URL.

    GET  ?scenario=case_001[&llm=0]        run a bundled case
    POST {"scenario": ...} or {"inputs": {...}, "options": {...}}
    GET  /                                  list scenarios

The report is returned inline and, when REPORT_BUCKET is set, saved to S3 as JSON and Markdown
with presigned links (PRESIGN_SECONDS, max 7 days for SigV4). Logs go to CloudWatch.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

from carerelay import service

log = logging.getLogger()
log.setLevel(logging.INFO)

REPORT_BUCKET = os.environ.get("REPORT_BUCKET")
PRESIGN_SECONDS = min(int(os.environ.get("PRESIGN_SECONDS", str(7 * 24 * 3600))), 7 * 24 * 3600)
_s3 = boto3.client("s3") if REPORT_BUCKET else None


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }


def _parse_event(event: dict) -> dict:
    http = (event.get("requestContext") or {}).get("http") or {}
    method = http.get("method", "GET").upper()
    qs = event.get("queryStringParameters") or {}
    if method == "POST" and event.get("body"):
        raw = event["body"]
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw)
    else:
        body = {}
    if "scenario" in qs and "scenario" not in body:
        body["scenario"] = qs["scenario"]
    if qs.get("llm") in ("0", "false", "no"):
        body.setdefault("options", {})["llm"] = False
    return body


def _save_report(report: dict) -> dict:
    if not _s3:
        return {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key_base = f"reports/{report.get('case_id') or 'upload'}/{stamp}-{uuid.uuid4().hex[:8]}"
    links = {}
    for ext, body, ctype in (
        ("json", json.dumps(report, indent=1), "application/json"),
        ("md", report["report"]["markdown"], "text/markdown"),
    ):
        key = f"{key_base}.{ext}"
        _s3.put_object(Bucket=REPORT_BUCKET, Key=key, Body=body.encode("utf-8"), ContentType=ctype, ServerSideEncryption="AES256")
        links[ext] = _s3.generate_presigned_url(
            "get_object", Params={"Bucket": REPORT_BUCKET, "Key": key}, ExpiresIn=PRESIGN_SECONDS
        )
    return {"bucket": REPORT_BUCKET, "key_base": key_base, "links": links, "expires_in_seconds": PRESIGN_SECONDS}


def handle(event: dict, context=None) -> dict:  # noqa: ARG001
    try:
        request = _parse_event(event)
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": f"bad request: {exc}"})

    if not request:
        return _response(200, {"scenarios": service.list_scenarios(), "usage": "GET ?scenario=case_001 or POST JSON"})

    try:
        report = service.handle(request)
    except service.ServiceError as exc:
        return _response(400, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.exception("pipeline failed")
        return _response(500, {"error": f"{type(exc).__name__}: {exc}"})

    report["saved"] = _save_report(report)
    log.info("case=%s elapsed=%ss stages=%s", report.get("case_id"), report["elapsed_seconds"],
             {k: v["status"] for k, v in report["stages"].items()})
    return _response(200, report)
