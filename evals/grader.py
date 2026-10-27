"""LLM-graded check for what string matching can't see: whether the summary keeps conditional risks
conditional.

The grader is Claude Haiku too (the only model this account can call), so it grades its own kind of
output. It quotes evidence before judging, which small models need, and every eval run calibrates it
on a known-bad and a known-good summary first (grader_calibration.json).

It also lists the cause-and-effect links it thinks are invented, but on Haiku that judgment failed
calibration (small prompt changes flipped it either way), so the eval reports those as notes only and
scores invented links with the deterministic check instead (validate.invented_connectives).
"""

import json
from pathlib import Path
from typing import Any

from onepager.bedrock import Usage, call_tool

TOOL_NAME = "record_grades"
MAX_TOKENS = 1200
HERE = Path(__file__).parent

SYSTEM_PROMPT = (HERE / "grader_prompt.md").read_text(encoding="utf-8").strip()

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "causal_phrases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["quote", "supported", "why"],
            },
        },
        "conditional_risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary_quote": {"type": ["string", "null"]},
                    "presented_as": {"type": "string", "enum": ["conditional", "happening_or_certain",
                                                                "not_mentioned"]},
                    "why": {"type": "string"},
                },
                "required": ["summary_quote", "presented_as", "why"],
            },
        },
    },
    "required": ["causal_phrases", "conditional_risks"],
}


def grade(client, model_id: str, notes: str, summary: str, conditional_risks: list[dict[str, str]],
          usage: Usage, headline: str | None = None) -> dict[str, Any]:
    """Links are judged in the headline (the only free text); conditional risks across the whole summary."""
    risks = "\n".join(f"{i}. {r['label']}: {r['condition']}" for i, r in enumerate(conditional_risks, 1))
    data = call_tool(
        client,
        model_id=model_id,
        system=SYSTEM_PROMPT,
        user=f"<notes>\n{notes}\n</notes>\n\n<summary>\n{summary}\n</summary>\n\n"
             f"<headline>\n{headline or summary}\n</headline>\n\n"
             f"<conditional_risks>\n{risks or '(none)'}\n</conditional_risks>",
        tool_name=TOOL_NAME,
        tool_description="Record the review of the summary.",
        schema=SCHEMA,
        max_tokens=MAX_TOKENS,
        usage=usage,
    )
    # Matched by position, since the grader is given them as a numbered list.
    graded = [g for g in data.get("conditional_risks", []) if isinstance(g, dict)]
    results = []
    for i, r in enumerate(conditional_risks):
        g = graded[i] if i < len(graded) else {}
        # A risk the grader skipped counts as a failure, so a lazy grade can't inflate the score.
        results.append({"label": r["label"], "correct": g.get("presented_as") in ("conditional", "not_mentioned"),
                        "reason": f"{g.get('presented_as', 'not graded')}: {g.get('why', '')}".strip(": ")})
    links = [str(p.get("quote")) for p in data.get("causal_phrases", [])
             if isinstance(p, dict) and p.get("supported") is False and str(p.get("quote", "")).strip()]
    return {"conditional_risks": results, "invented_links": links}


def calibrate(client, model_id: str, usage: Usage) -> list[dict[str, Any]]:
    """Grade summaries whose right answer is known. If the grader gets these wrong, don't trust its scores."""
    results = []
    for case in json.loads((HERE / "grader_calibration.json").read_text(encoding="utf-8")):
        notes = (HERE / case["notes"]).read_text(encoding="utf-8")
        g = grade(client, model_id, notes, case["summary"], case["conditional_risks"], usage, case["headline"])
        got = {"conditional_correct": [r["correct"] for r in g["conditional_risks"]]}
        results.append({"id": case["id"], "passed": got == case["expect"], "expected": case["expect"], "got": got})
    return results
