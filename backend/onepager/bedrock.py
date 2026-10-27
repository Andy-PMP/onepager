"""Thin wrapper over the Bedrock Converse API: one forced tool call per request."""

from dataclasses import dataclass
from typing import Any


class ModelError(RuntimeError):
    """The model call failed or didn't return the expected tool call."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


# Errors worth one more try. Anything else (access denied, bad request) will fail the same way again.
_RETRYABLE_CODES = {"ThrottlingException", "ServiceUnavailableException", "InternalServerException",
                    "ModelTimeoutException", "ModelNotReadyException", "ModelErrorException"}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += usage.get("inputTokens", 0)
        self.output_tokens += usage.get("outputTokens", 0)
        self.calls += 1

    def to_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "calls": self.calls}


def make_client(region: str | None = None):
    import boto3
    from botocore.config import Config

    # Keep well inside the 30s API Gateway limit: one quick retry for throttling, no long waits.
    config = Config(connect_timeout=5, read_timeout=25, retries={"mode": "standard", "max_attempts": 2})
    return boto3.client("bedrock-runtime", region_name=region, config=config)


def call_tool(
    client,
    *,
    model_id: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    schema: dict[str, Any],
    max_tokens: int,
    usage: Usage,
) -> dict[str, Any]:
    """Force the model to call `tool_name` and return the tool input it produced."""
    try:
        response = client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
            toolConfig={
                "tools": [{"toolSpec": {"name": tool_name, "description": tool_description,
                                        "inputSchema": {"json": schema}}}],
                "toolChoice": {"tool": {"name": tool_name}},
            },
        )
    except Exception as e:  # botocore raises many types; callers only need to know it failed
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        raise ModelError(f"Bedrock call failed: {code}", retryable=code in _RETRYABLE_CODES) from e

    usage.add(response.get("usage", {}))
    if response.get("stopReason") == "max_tokens":
        raise ModelError(f"{tool_name}: output hit the {max_tokens}-token limit")
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == tool_name:
            return tool_use.get("input") or {}
    raise ModelError(f"Model did not call {tool_name}")
