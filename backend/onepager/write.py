"""Step 3: the LLM writes the executive summary from the facts and the fixed statuses.

Only the summary is written here. The lists (accomplishments, next steps, risks, asks) come
straight from extraction, which already rewrites them in plain English: a second rewrite
would add cost and another chance to invent something, without adding much.
"""

import json
from pathlib import Path
from typing import Any

from .bedrock import Usage, call_tool
from .rules import Scorecard
from .schema import Facts, Risk

TOOL_NAME = "write_summary"
MAX_TOKENS = 600
MAX_RISKS = 5

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}

WRITE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"executive_summary": {"type": "string", "description": "3-4 sentences"}},
    "required": ["executive_summary"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "write_system.md").read_text(encoding="utf-8").strip()


def top_risks(facts: Facts, limit: int = MAX_RISKS) -> list[Risk]:
    """Open risks, highest impact first."""
    open_risks = [r for r in facts.risks or [] if r.state != "closed"]
    return sorted(open_risks, key=lambda r: _IMPACT_ORDER.get(r.impact, 3))[:limit]


def statuses_for_prompt(card: Scorecard) -> str:
    lines = [f"overall: {card.overall.value}{' (low confidence)' if card.low_confidence else ''}"
             f" - {card.overall_reason}"]
    lines += [f"{d.dimension}: {d.status.value} - {d.reason}" for d in card.dimensions]
    return "\n".join(lines)


def write(client, model_id: str, facts: Facts, card: Scorecard, usage: Usage,
          feedback: str | None = None) -> dict[str, Any]:
    user = (f"<facts>\n{json.dumps(facts.to_dict(), indent=1)}\n</facts>\n\n"
            f"<statuses>\n{statuses_for_prompt(card)}\n</statuses>")
    if feedback:
        user += f"\n\nYour previous draft was rejected:\n{feedback}\nFix these problems and call {TOOL_NAME} again."
    return call_tool(
        client,
        model_id=model_id,
        system=SYSTEM_PROMPT,
        user=user,
        tool_name=TOOL_NAME,
        tool_description="Write the executive summary of the one-pager.",
        schema=WRITE_JSON_SCHEMA,
        max_tokens=MAX_TOKENS,
        usage=usage,
    )
