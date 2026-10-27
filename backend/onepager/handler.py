"""Lambda entry point for POST /generate (API Gateway HTTP API, payload v2).

Logs never include the notes or the generated one-pager: only sizes, tokens, timing, outcome and
which rule fired per dimension.
"""

import base64
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from . import limits
from .bedrock import make_client
from .pipeline import InputError, PipelineError, check_input, generate

_bedrock = None
_dynamodb = None


def _clients():
    global _bedrock, _dynamodb
    if _bedrock is None:
        import boto3

        _bedrock = make_client()
        _dynamodb = boto3.client("dynamodb")
    return _bedrock, _dynamodb


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def _log(**fields: Any) -> None:
    print(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), **fields}))


def _notes_from(event: dict[str, Any]) -> Any:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise InputError("Send JSON like {\"notes\": \"...\"}.") from None
    return body.get("notes") if isinstance(body, dict) else None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        notes = check_input(_notes_from(event))
    except InputError as e:
        _log(event="rejected", reason="input")
        return _response(400, {"error": str(e)})

    bedrock, dynamodb = _clients()
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
    try:
        limits.consume(dynamodb, os.environ["TABLE_NAME"], ip, os.environ["IP_HASH_SALT"],
                       int(os.environ["PER_VISITOR_CAP"]), int(os.environ["DAILY_CAP"]), datetime.now(UTC))
    except limits.LimitReached as e:
        _log(event="rejected", reason=f"{e.scope}_cap", chars=len(notes))
        return _response(429, {"error": str(e), "limit": e.scope})
    except Exception as e:  # can't count the request, so don't spend money on it
        _log(event="rejected", reason="counter_error", error=type(e).__name__)
        return _response(503, {"error": "The demo is unavailable right now. Try a sample."})

    try:
        result = generate(bedrock, os.environ["MODEL_ID"], notes,
                          time_left=lambda: context.get_remaining_time_in_millis() / 1000)
    except PipelineError as e:
        # e.detail can quote generated text, so only its stage ("extract" or "write") is logged.
        _log(event="generate", ok=False, chars=len(notes), stage=e.detail.split(":")[0],
             latency_ms=round((time.monotonic() - started) * 1000))
        return _response(502, {"error": f"{e} Please try again, or try a sample."})
    except Exception as e:
        _log(event="generate", ok=False, chars=len(notes), error=type(e).__name__,
             latency_ms=round((time.monotonic() - started) * 1000))
        return _response(500, {"error": "Something went wrong. Please try again, or try a sample."})

    _log(event="generate", **result.log)
    return _response(200, result.onepager)
