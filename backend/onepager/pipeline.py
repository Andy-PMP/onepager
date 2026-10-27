"""Extract (LLM) -> score (rules) -> write (LLM) -> validate (code), with one retry per LLM step."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .bedrock import ModelError, Usage
from .extract import extract
from .rules import Scorecard, score
from .schema import Facts, SchemaError
from .validate import check_texts, parse_summary
from .write import top_risks, write

MAX_INPUT_CHARS = 6000
# Only retry a step if at least this much time is left (the API Gateway limit is 30s).
MIN_SECONDS_FOR_RETRY = 12.0

STATUS_LABELS = {"green": "Green", "amber": "Amber", "red": "Red", "unknown": "Unknown"}


class InputError(ValueError):
    """The notes are empty or too long."""


class PipelineError(RuntimeError):
    """The pipeline couldn't produce a one-pager. The message is safe to show; `detail` is for logs."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


@dataclass
class Result:
    onepager: dict[str, Any]
    usage: Usage
    log: dict[str, Any]


def check_input(notes: Any) -> str:
    if not isinstance(notes, str) or not notes.strip():
        raise InputError("Paste some project notes first.")
    if len(notes) > MAX_INPUT_CHARS:
        raise InputError(f"Notes are limited to {MAX_INPUT_CHARS:,} characters.")
    return notes


def generate(client, model_id: str, notes: str, time_left: Callable[[], float] | None = None) -> Result:
    started = time.monotonic()
    notes = check_input(notes)
    usage = Usage()
    retries: list[str] = []

    def can_retry() -> bool:
        return time_left is None or time_left() >= MIN_SECONDS_FOR_RETRY

    # Step 1: extract
    try:
        facts = extract(client, model_id, notes, usage)
    except (SchemaError, ModelError) as e:
        if not can_retry() or not getattr(e, "retryable", True):
            raise PipelineError("Couldn't read the notes.", f"extract: {e}") from e
        retries.append("extract")
        try:
            facts = extract(client, model_id, notes, usage, feedback=str(e))
        except (SchemaError, ModelError) as e2:
            raise PipelineError("Couldn't read the notes.", f"extract retry: {e2}") from e2

    # Step 2: score
    card = score(facts)

    # Steps 3 and 4: write the summary, validate it, retry once with the problems as feedback
    summary, problems, retryable = _write_and_check(client, model_id, notes, facts, card, usage)
    if problems and retryable and can_retry():
        retries.append("write")
        retry_summary, retry_problems, _ = _write_and_check(client, model_id, notes, facts, card, usage,
                                                            feedback="\n".join(f"- {p}" for p in problems))
        if retry_summary is not None and (summary is None or len(retry_problems) <= len(problems)):
            summary, problems = retry_summary, retry_problems
    if summary is None:
        raise PipelineError("Couldn't write the one-pager.", "write: " + "; ".join(problems))

    # The extracted lists are checked too. A problem there can only be flagged: rewriting the summary won't fix it.
    problems += check_texts(_list_texts(facts), notes, card)

    onepager = assemble(facts, card, summary, problems)
    latency_ms = round((time.monotonic() - started) * 1000)
    onepager["meta"] = {"model": model_id, "usage": usage.to_dict(), "latency_ms": latency_ms}
    log = {
        "chars": len(notes),
        **usage.to_dict(),
        "latency_ms": latency_ms,
        "ok": True,
        "retries": retries,
        "warnings": len(problems),
        "rules": {d.dimension: d.rule for d in card.dimensions},
    }
    return Result(onepager, usage, log)


def _write_and_check(client, model_id, notes, facts, card, usage, feedback=None):
    try:
        summary = parse_summary(write(client, model_id, facts, card, usage, feedback))
    except (SchemaError, ModelError) as e:
        return None, [str(e)], getattr(e, "retryable", True)
    return summary, check_texts([summary], notes, card), True


def _list_texts(facts: Facts) -> list[str]:
    risks = [x for r in top_risks(facts) for x in (r.description, r.mitigation) if x]
    return [*facts.accomplishments, *facts.next_steps, *facts.asks, *risks]


def assemble(facts: Facts, card: Scorecard, summary: str, problems: list[str]) -> dict[str, Any]:
    risks = [
        {"summary": r.description, "kind": r.kind or "risk", "impact": r.impact, "owner": r.owner,
         "mitigation": r.mitigation}
        for r in top_risks(facts)
    ]
    onepager = {
        "project_name": facts.project_name,
        "reporting_period": facts.reporting_period,
        "as_of_date": facts.as_of_date.isoformat() if facts.as_of_date else None,
        **card.to_dict(),
        "executive_summary": summary,
        "accomplishments": facts.accomplishments,
        "next_steps": facts.next_steps,
        "risks": risks,
        "asks": facts.asks,
        "warnings": (["Some details in this one-pager couldn't be verified against your notes. Check figures "
                      "and dates before using it."] if problems else []),
        "validation_problems": problems,
    }
    onepager["markdown"] = to_markdown(onepager)
    return onepager


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- {x}" for x in items] if items else [f"- _{empty}_"]


def to_markdown(p: dict[str, Any]) -> str:
    """The copy-as-Markdown version. Built here so the frontend and the eval use the same text."""
    title = p["project_name"] or "Project status"
    period = p["reporting_period"] or p["as_of_date"]
    overall = STATUS_LABELS[p["overall"]] + (" (low confidence)" if p["low_confidence"] else "")
    lines = [f"# {title}", ""]
    if period:
        lines += [f"**Reporting period:** {period}  "]
    lines += [f"**Overall status:** {overall}", "", "## Status by dimension", "",
              "| Dimension | Status | Why |", "|---|---|---|"]
    lines += [f"| {d['dimension'].capitalize()} | {STATUS_LABELS[d['status']]} | {d['reason']} |"
              for d in p["dimensions"]]
    lines += ["", "## Executive summary", "", p["executive_summary"], "",
              "## Accomplishments this period", "", *_bullets(p["accomplishments"], "None listed"), "",
              "## Next steps", "", *_bullets(p["next_steps"], "None listed"), "",
              "## Top risks and issues", ""]
    if p["risks"]:
        for r in p["risks"]:
            impact = f" ({r['impact']} impact)" if r["impact"] else ""
            lines.append(f"- **{r['summary']}**{impact}  ")
            lines.append(f"  Owner: {r['owner'] or 'not stated'} · Mitigation: {r['mitigation'] or 'not stated'}")
    else:
        lines.append("- _None listed_")
    lines += ["", "## Decisions and asks for leadership", "", *_bullets(p["asks"], "None"), ""]
    if p["gaps"]:
        lines += ["## Gaps in the notes", "", *[f"- {g}" for g in p["gaps"]], ""]
    if p["warnings"]:
        lines += [f"> ⚠️ {w}" for w in p["warnings"]] + [""]
    return "\n".join(lines)
