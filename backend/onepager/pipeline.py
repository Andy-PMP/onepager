"""Extract (LLM) -> score (rules) -> write (LLM) -> validate (code), with one retry per LLM step."""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from .bedrock import ModelError, Usage
from .extract import extract
from .rules import Scorecard, load_thresholds, score
from .schema import Facts, SchemaError
from .tables import apply_tables, parse_tables
from .validate import (
    check_texts,
    ground_facts,
    headline_style_problems,
    invented_connectives,
    parse_headline,
    unsupported_attributions,
    unsupported_figures,
)
from .write import facts_paragraph, top_risks, write

MAX_INPUT_CHARS = 6000
# Only retry a step if at least this much time is left (the API Gateway limit is 30s).
MIN_SECONDS_FOR_RETRY = 12.0

STATUS_LABELS = {"green": "Green", "amber": "Amber", "red": "Red", "unknown": "Unknown"}
# Markdown has no icons, so the export uses emoji with distinct shapes (not just colours, for colour-blind
# readers), matching the page icons: check, warning triangle, cross, question mark.
STATUS_EMOJI = {"green": "✅", "amber": "⚠️", "red": "❌", "unknown": "❔"}


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
    # Why each retry happened. Can quote generated text, so it's for local evals only, never logs.
    retry_reasons: list[str] = field(default_factory=list)
    # Extracted dates and figures dropped because the notes don't contain them (same caveat).
    dropped: list[str] = field(default_factory=list)


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
    retry_reasons: list[str] = []

    def can_retry() -> bool:
        return time_left is None or time_left() >= MIN_SECONDS_FOR_RETRY

    # Step 1: extract, then check it in code before anything depends on it
    try:
        facts = extract(client, model_id, notes, usage)
    except (SchemaError, ModelError) as e:
        if not can_retry() or not getattr(e, "retryable", True):
            raise PipelineError("Couldn't read the notes.", f"extract: {e}") from e
        retries.append("extract")
        retry_reasons.append(f"extract: {e}")
        try:
            facts = extract(client, model_id, notes, usage, feedback=str(e))
        except (SchemaError, ModelError) as e2:
            raise PipelineError("Couldn't read the notes.", f"extract retry: {e2}") from e2

    facts, dropped = ground_facts(facts, notes)
    list_problems = unsupported_figures(_list_texts(facts), [notes])
    if list_problems and not retries and can_retry():
        retries.append("extract")
        retry_reasons += [f"extract: {p}" for p in list_problems]
        feedback = ("Some text items contain figures or dates that aren't in the notes: "
                    + "; ".join(list_problems) + ". Use only figures and dates the notes state.")
        try:
            retry_facts, retry_dropped = ground_facts(extract(client, model_id, notes, usage, feedback), notes)
            if len(unsupported_figures(_list_texts(retry_facts), [notes])) < len(list_problems):
                facts, dropped = retry_facts, retry_dropped
        except (SchemaError, ModelError):
            pass  # keep the first extraction; the final check flags what's left
    facts = _drop_duplicate_decisions(_keep_real_asks(facts))
    # Tables are parsed in code and replace what the model read from them; totals computed here are
    # grounded by construction, so this runs after ground_facts.
    t = load_thresholds()
    facts = apply_tables(facts, parse_tables(notes), notes, t.accomplishment_window_days, t.next_steps_window_days)
    facts = _drop_change_requests_listed_as_risks(facts, notes)
    facts = _drop_unforecast_costs_owned_by_change_requests(facts)

    # Step 2: score
    card = score(facts, t)
    card = replace(card, gaps=card.gaps + _coverage_gaps(facts, notes))

    # Steps 3 and 4: the model writes a one-sentence headline; validate it and retry once with the problems
    # as feedback. Correctness problems become warnings if they survive the retry; style problems only
    # trigger the retry. Code then adds the factual sentences.
    headline, problems, style, retryable = _write_and_check(client, model_id, notes, facts, card, usage)
    if (problems or style) and retryable and can_retry():
        retries.append("write")
        retry_reasons += [f"write: {p}" for p in problems + style]
        retry = _write_and_check(client, model_id, notes, facts, card, usage,
                                 feedback="\n".join(f"- {p}" for p in problems + style))
        retry_headline, retry_problems, retry_style, _ = retry
        if retry_headline is not None and (headline is None or (len(retry_problems), len(retry_style))
                                           <= (len(problems), len(style))):
            headline, problems, style = retry_headline, retry_problems, retry_style
    # A headline that still breaks a style rule after its rewrite (an invented link, a repeat of the facts),
    # or that couldn't be written at all, is dropped: the code-built sentences are a complete summary on their
    # own. Its problems go with it, since it isn't shown.
    headline_dropped = headline is None or bool(style)
    summary = (facts_paragraph(facts, card) if headline_dropped
               else f"{headline} {facts_paragraph(facts, card, already_said=headline)}")
    if headline_dropped:
        headline, problems = "", []

    # The extracted lists are checked too. A problem there can only be flagged: rewriting the summary won't fix it.
    problems += check_texts(_list_texts(facts), notes, card)

    onepager = assemble(facts, card, summary, problems)
    onepager["headline"] = humanize_dates(headline, facts.as_of_date)  # the only free-text part, for graders
    latency_ms = round((time.monotonic() - started) * 1000)
    onepager["meta"] = {"model": model_id, "usage": usage.to_dict(), "latency_ms": latency_ms}
    log = {
        "chars": len(notes),
        **usage.to_dict(),
        "latency_ms": latency_ms,
        "ok": True,
        "retries": retries,
        "warnings": len(problems),
        "dropped_facts": len(dropped),
        "headline_dropped": headline_dropped,
        "rules": {d.dimension: d.rule for d in card.dimensions},
    }
    return Result(onepager, usage, log, retry_reasons, dropped)


def _write_and_check(client, model_id, notes, facts, card, usage, feedback=None):
    try:
        headline = parse_headline(write(client, model_id, facts, card, usage, feedback))
    except (SchemaError, ModelError) as e:
        return None, [str(e)], [], getattr(e, "retryable", True)
    problems = check_texts([headline], notes, card) + unsupported_attributions(headline, facts.asks, notes)
    style = (headline_style_problems(headline, bool(facts.asks), facts_paragraph(facts, card))
             + invented_connectives(headline, notes))
    return headline, problems, style, True


_WORD = re.compile(r"[a-z0-9]{4,}")
# Identifiers like CR-14 or JIRA-123: sharing one with an ask means it's the same item.
_IDENTIFIER = re.compile(r"\b[a-z]{1,10}-?\d+\b")


# An ask is a request for a decision or action. "Hannah is asking the issuer about an earlier slot" isn't one,
# and the model kept filing it as one, so asks without a decision or action word become next steps.
_ASK_VERB = re.compile(r"\b(approv\w*|decid\w*|decision|sign[- ]?off|assign\w*|confirm\w*|authori[sz]\w*|fund\w*|"
                       r"choose|agree\w*|endorse\w*|announce\w*|need\w*|request\w*|allocat\w*|escalat\w*|"
                       r"defer\w*|support)\b", re.IGNORECASE)


def _drop_change_requests_listed_as_risks(facts: Facts, notes: str) -> Facts:
    """A pending change request belongs in scope, not risks (the model turned CR-03 into an inverted risk).
    Kept only if the notes themselves call that change a risk."""
    if not facts.risks or not facts.scope_changes:
        return facts
    cr_ids = {i.replace("-", "") for c in facts.scope_changes
              for i in _IDENTIFIER.findall(f"{c.title or ''} {c.description}".lower())}
    called_risk = {i.replace("-", "") for line in notes.lower().splitlines() if "risk" in line
                   for i in _IDENTIFIER.findall(line)}

    def is_change_request(r) -> bool:
        ids = {i.replace("-", "") for i in _IDENTIFIER.findall(f"{r.title or ''} {r.description}".lower())}
        return bool(ids & cr_ids) and not ids & called_risk

    kept = [r for r in facts.risks if not is_change_request(r)]
    return replace(facts, risks=kept or None) if len(kept) != len(facts.risks) else facts


def _drop_unforecast_costs_owned_by_change_requests(facts: Facts) -> Facts:
    """A pending change request's cost gets its own 'if approved' gap; don't count it again as a known cost
    left out of the forecast (Harbor Street showed CR-03's $62,000 twice)."""
    b = facts.budget
    if not b or not b.unforecast_costs or not facts.scope_changes:
        return facts
    cr_ids = {i.replace("-", "") for c in facts.scope_changes if c.cost
              for i in _IDENTIFIER.findall(f"{c.title or ''} {c.description}".lower())}
    kept = [u for u in b.unforecast_costs
            if not {i.replace("-", "") for i in _IDENTIFIER.findall(u.description.lower())} & cr_ids]
    return replace(facts, budget=replace(b, unforecast_costs=kept)) if len(kept) != len(b.unforecast_costs) \
        else facts


def _coverage_gaps(facts: Facts, notes: str) -> list[str]:
    """Topics the notes clearly cover but nothing was read from. Rare now that tables are parsed in code,
    but a budget mentioned with figures and no planned total is worth flagging rather than staying silent."""
    gaps = []
    if (re.search(r"\bbudget\b", notes, re.IGNORECASE) and re.search(r"[$€£]\s?\d|\d[\d,]{3,}", notes)
            and not (facts.budget and facts.budget.planned is not None)):
        gaps.append("The notes mention a budget with figures, but no planned total could be read from them.")
    return gaps


def _keep_real_asks(facts: Facts) -> Facts:
    asks = [a for a in facts.asks if _ASK_VERB.search(a)]
    moved = [a for a in facts.asks if not _ASK_VERB.search(a)]
    return replace(facts, asks=asks, next_steps=facts.next_steps + moved) if moved else facts


def _drop_duplicate_decisions(facts: Facts) -> Facts:
    """An open decision that restates an ask is noise; the prompt says so, but code makes sure."""
    ask_words = [set(_WORD.findall(a.lower())) for a in facts.asks]
    ask_ids = {i.replace("-", "") for a in facts.asks for i in _IDENTIFIER.findall(a.lower())}

    def duplicate(decision: str) -> bool:
        if {i.replace("-", "") for i in _IDENTIFIER.findall(decision.lower())} & ask_ids:
            return True
        words = set(_WORD.findall(decision.lower()))
        return bool(words) and any(len(words & a) / len(words) >= 0.5 for a in ask_words)

    return replace(facts, open_decisions=[d for d in facts.open_decisions if not duplicate(d)])


def _list_texts(facts: Facts) -> list[str]:
    risks = [x for r in top_risks(facts) for x in (r.description, r.mitigation) if x]
    return [*facts.accomplishments, *facts.next_steps, *facts.asks, *facts.open_decisions, *risks]


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def humanize_dates(text: str | None, as_of: date | None) -> str | None:
    """The model writes YYYY-MM-DD (which it gets right); code turns it into "11 December" for reading."""
    if text is None:
        return None

    def fmt(m: re.Match) -> str:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return m.group(0)
        same_year = as_of is not None and d.year == as_of.year
        return f"{d.day} {d:%B}" if same_year else f"{d.day} {d:%B %Y}"

    return _ISO_DATE.sub(fmt, text)


def assemble(facts: Facts, card: Scorecard, summary: str, problems: list[str]) -> dict[str, Any]:
    def h(text: str | None) -> str | None:
        return humanize_dates(text, facts.as_of_date)

    risks = [
        {"summary": h(r.description), "kind": r.kind or "risk", "impact": r.impact, "owner": r.owner,
         "mitigation": h(r.mitigation)}
        for r in top_risks(facts)
    ]
    scorecard = card.to_dict()
    for d in scorecard["dimensions"]:
        d["reason"] = h(d["reason"])
    scorecard["gaps"] = [h(g) for g in scorecard["gaps"]]
    onepager = {
        "project_name": facts.project_name,
        "as_of_date": facts.as_of_date.isoformat() if facts.as_of_date else None,
        **scorecard,
        "executive_summary": h(summary),
        "accomplishments": [h(x) for x in facts.accomplishments],
        "next_steps": [h(x) for x in facts.next_steps],
        "risks": risks,
        "asks": [h(x) for x in facts.asks],
        "open_decisions": [h(x) for x in facts.open_decisions],
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
    overall = (f"{STATUS_EMOJI[p['overall']]} {STATUS_LABELS[p['overall']]}"
               + (" (low confidence)" if p["low_confidence"] else ""))
    strip = " · ".join(f"{STATUS_EMOJI[d['status']]} {d['dimension'].capitalize()}" for d in p["dimensions"])
    lines = [f"# {title}", ""]
    if p["as_of_date"]:
        as_of = date.fromisoformat(p["as_of_date"])
        lines += [f"**As of:** {as_of.day} {as_of:%B %Y}  "]
    lines += [f"**Overall status:** {overall}  ", strip, "", "## Executive summary", "", p["executive_summary"], "",
              "## Status by dimension", "", "| Dimension | Status | Why |", "|---|---|---|"]
    lines += [f"| {d['dimension'].capitalize()} | {STATUS_EMOJI[d['status']]} {STATUS_LABELS[d['status']]} "
              f"| {d['reason']} |" for d in p["dimensions"]]
    lines += ["",
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
    if p["open_decisions"]:
        lines += ["**Open decisions, not yet put to leadership:**", "", *_bullets(p["open_decisions"], ""), ""]
    if p["gaps"]:
        lines += ["## Gaps in the notes", "", *[f"- {g}" for g in p["gaps"]], ""]
    if p["warnings"]:
        lines += [f"> ⚠️ {w}" for w in p["warnings"]] + [""]
    return "\n".join(lines)
