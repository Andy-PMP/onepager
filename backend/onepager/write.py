"""Step 3: the executive summary. Code writes the facts; the LLM writes one headline sentence.

When the model wrote the whole summary it kept inventing links between true facts ("slipped, creating
a collision"), and no prompt rule held. Now each rule supplies a plain clause from the facts it scored,
code assembles them into sentences, and the model only writes the opening line, which the validators
check on its own.

The lists (accomplishments, next steps, risks, asks) come straight from extraction.
"""

import json
from pathlib import Path
from typing import Any

from .bedrock import Usage, call_tool
from .rules import Scorecard, Status
from .schema import Facts, Risk
from .validate import HEADLINE_MAX_WORDS

TOOL_NAME = "write_headline"
MAX_TOKENS = 300
MAX_RISKS = 5
MAX_ASKS_CHARS = 160

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}

WRITE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"headline": {"type": "string", "description": "One sentence"}},
    "required": ["headline"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "write_system.md").read_text(encoding="utf-8").strip()


def top_risks(facts: Facts, limit: int = MAX_RISKS) -> list[Risk]:
    """Open risks, highest impact first."""
    open_risks = [r for r in facts.risks or [] if r.state != "closed"]
    return sorted(open_risks, key=lambda r: _IMPACT_ORDER.get(r.impact, 3))[:limit]


def _list(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]


def _sentence(clauses: list[str]) -> str:
    if not clauses:
        return ""
    if len(clauses) == 1:
        text = clauses[0]
    elif len(clauses) == 2:
        text = f"{clauses[0]}, and {clauses[1]}"
    else:
        text = "; ".join(clauses[:-1]) + f"; and {clauses[-1]}"
    return text[0].upper() + text[1:] + "."


def facts_paragraph(facts: Facts, card: Scorecard) -> str:
    """The deterministic part of the summary: red items, then amber items, then gaps in coverage, then asks."""
    red = [d.summary for d in card.dimensions if d.status is Status.RED and d.summary]
    amber = [d.summary for d in card.dimensions if d.status is Status.AMBER and d.summary]
    unknown = [d.dimension for d in card.dimensions if d.status is Status.UNKNOWN]
    sentences = [_sentence(red), _sentence(amber)]
    if unknown:
        sentences.append(f"The notes don't cover {_list(unknown)}"
                         + (", so the overall status is low-confidence." if card.low_confidence else "."))
    elif not red and not amber:
        sentences.append("Schedule, budget, scope and risk are all within tolerance.")
    if facts.asks:
        asks = "; ".join(a.rstrip(".") for a in facts.asks)
        n = len(facts.asks)
        sentences.append(f"Decisions needed: {asks}." if len(asks) <= MAX_ASKS_CHARS
                         else f"{n} decisions are needed (listed below).")
    return " ".join(s for s in sentences if s)


def statuses_for_prompt(card: Scorecard) -> str:
    lines = [f"overall: {card.overall.value}{' (low confidence)' if card.low_confidence else ''}"
             f" - {card.overall_reason}"]
    lines += [f"{d.dimension}: {d.status.value} - {d.reason}" for d in card.dimensions]
    return "\n".join(lines)


def checklist_for_prompt(facts: Facts, card: Scorecard) -> str:
    """Spell out the rules for this report. Small models follow a concrete checklist far more reliably than
    "if X then Y" rules in the system prompt."""
    items = [f"One sentence, at most {HEADLINE_MAX_WORDS} words: the single most important thing about this "
             "project right now, in plain words.",
             f"Code adds these facts right after your sentence, so don't repeat their details: "
             f"\"{facts_paragraph(facts, card)}\"",
             "Don't name status colours (green, amber, red); the page shows them with icons."]
    for r in top_risks(facts):
        if r.condition:
            items.append(f"Conditional risk, not happening yet: '{r.title or r.description}' hits only "
                         f"{r.condition}. If you mention it, present it as a possibility with that condition.")
    if not facts.asks:
        items.append("There are no asks. Don't mention leadership, a sponsor or a steering committee, "
                     "and don't suggest any decision or action for them.")
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
        tool_description="Write the headline sentence of the executive summary.",
        schema=WRITE_JSON_SCHEMA,
        max_tokens=MAX_TOKENS,
        usage=usage,
    )
