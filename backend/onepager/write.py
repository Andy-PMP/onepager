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
# Models count words badly, so the prompt aims well under the limit the eval enforces.
SUMMARY_TARGET_WORDS = 65
SUMMARY_MAX_WORDS = 100

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


def checklist_for_prompt(facts: Facts, card: Scorecard) -> str:
    """Spell out the conditional rules for this report. Small models follow a concrete checklist far more
    reliably than "if X then Y" rules in the system prompt."""
    unknown = [d.dimension for d in card.dimensions if d.status.value == "unknown"]
    items = [f"Open by stating the overall status: {card.overall.value}."]
    if unknown:
        items.append(f"Say that the notes don't cover: {', '.join(unknown)}.")
    if card.low_confidence:
        items.append("Say that the overall status is low-confidence because of the missing information.")
    if facts.asks:
        items.append(f"End with the {len(facts.asks)} ask(s) for leadership listed in <facts>.")
    else:
        items.append("There are no asks. Don't mention leadership, a sponsor or a steering committee, "
                     "and don't suggest any decision or action for them.")
    items.append(f"About {SUMMARY_TARGET_WORDS} words. Keep each sentence short.")
    return "\n".join(f"- {item}" for item in items)


def write(client, model_id: str, facts: Facts, card: Scorecard, usage: Usage,
          feedback: str | None = None) -> dict[str, Any]:
    user = (f"<facts>\n{json.dumps(facts.to_dict(), indent=1)}\n</facts>\n\n"
            f"<statuses>\n{statuses_for_prompt(card)}\n</statuses>\n\n"
            f"<checklist>\n{checklist_for_prompt(facts, card)}\n</checklist>")
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
