"""Step 1: the LLM turns messy notes into Facts. It extracts; it never judges status."""

import re
from pathlib import Path

from .bedrock import Usage, call_tool
from .schema import EXTRACTION_JSON_SCHEMA, Facts, parse_facts

TOOL_NAME = "record_facts"
MAX_TOKENS = 2000

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "extract_system.md").read_text(encoding="utf-8").strip()

_TAG = re.compile(r"</?\s*notes\s*>", re.IGNORECASE)


def wrap_notes(notes: str) -> str:
    """Delimit the notes as data. Strip lookalike tags so the notes can't close the block early."""
    return f"<notes>\n{_TAG.sub('[tag removed]', notes)}\n</notes>"


def extract(client, model_id: str, notes: str, usage: Usage, feedback: str | None = None) -> Facts:
    user = wrap_notes(notes)
    if feedback:
        user += f"\n\nYour previous attempt was rejected: {feedback}\nCall record_facts again with valid data."
    data = call_tool(
        client,
        model_id=model_id,
        system=SYSTEM_PROMPT,
        user=user,
        tool_name=TOOL_NAME,
        tool_description="Record the facts found in the project notes.",
        schema=EXTRACTION_JSON_SCHEMA,
        max_tokens=MAX_TOKENS,
        usage=usage,
    )
    return parse_facts(data)
