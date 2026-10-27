"""Step 4: check the generated text in code before it reaches the reader.

- Shape: the headline tool output matches the expected structure.
- Status: any status color the text mentions matches the computed status.
- Figures: every number and date in the text appears in the notes or in a rule's reason.
- Attributions and links: approvers and cause-and-effect the notes don't state.

The figure check is deliberately conservative. It normalises formats (2.4M = $2,400,000,
4/24 = 24 April) and allows rounding, but anything it can't trace back to the input is flagged.
"""

import re
from dataclasses import replace
from datetime import date
from typing import Any

from .rules import Scorecard, Status
from .schema import Facts, SchemaError

MAX_HEADLINE_CHARS = 400


def parse_headline(data: Any) -> str:
    if not isinstance(data, dict) or set(data) - {"headline"}:
        raise SchemaError("expected an object with only headline")
    headline = data.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise SchemaError("headline must be a non-empty string")
    if len(headline) > MAX_HEADLINE_CHARS:
        raise SchemaError(f"headline is longer than {MAX_HEADLINE_CHARS} characters")
    if "<" in headline and ">" in headline:
        raise SchemaError("headline contains markup")
    return headline.strip()


# --- Status contradictions ----------------------------------------------------------------

_COLORS = {"green": Status.GREEN, "amber": Status.AMBER, "yellow": Status.AMBER, "red": Status.RED}
_COLOR_RE = re.compile(r"\b(green|amber|yellow|red)\b", re.IGNORECASE)
DIMENSION_WORDS = {
    dim: re.compile(pattern, re.IGNORECASE)
    for dim, pattern in {
        "schedule": r"\b(schedul|timeline|milestone|dates?\b|deadline|go-live|cutover|launch|slip|delay|late\b)",
        "budget": r"\b(budget|cost|spend|financ|overrun|forecast)",
        "scope": r"\b(scope|change request)",
        "risk": r"\b(risks?\b|issues?\b)",
    }.items()
}
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def find_contradictions(texts: list[str], card: Scorecard) -> list[str]:
    """A color is fine if it matches the overall status or any dimension the sentence mentions."""
    statuses = {d.dimension: d.status for d in card.dimensions}
    problems = []
    for text in texts:
        for sentence in _SENTENCE_RE.split(text):
            mentioned = [dim for dim, pattern in DIMENSION_WORDS.items() if pattern.search(sentence)]
            allowed = {card.overall} | {statuses[d] for d in mentioned}
            for match in _COLOR_RE.finditer(sentence):
                color = _COLORS[match.group(1).lower()]
                if color not in allowed:
                    problems.append(f'Says "{match.group(1)}", which contradicts the computed status: '
                                    f'"{sentence.strip()}"')
    return problems


# --- Unsupported figures ------------------------------------------------------------------

_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_YEAR = r"(?:,?\s+\d{4})?"
_DASH = r"\s*(?:-|–|—|to)\s*"
_DATE_PATTERNS = [
    ("iso", re.compile(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b")),
    # Ranges first, so "12-13 December" isn't read as a bare 12 followed by 13 December.
    ("day_range_month", re.compile(rf"\b(\d{{1,2}}){_DASH}(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}\b\.?{_YEAR}",
                                   re.IGNORECASE)),
    ("month_day_range", re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}}){_DASH}(\d{{1,2}})(?:st|nd|rd|th)?\b{_YEAR}",
                                   re.IGNORECASE)),
    ("month_day", re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b{_YEAR}", re.IGNORECASE)),
    ("day_month", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b\.?{_YEAR}", re.IGNORECASE)),
    ("numeric", re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")),
]
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_NUMBER = re.compile(
    r"(?<![\w.])([$€£])?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(%|percent|bn|billion|million|thousand|k|m)?(?!\w)",
    re.IGNORECASE,
)
_MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
# Bare small integers ("two cutovers", "3 sessions") are too noisy to police.
_IGNORE_BARE_INTS_UP_TO = 10


def _valid(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def find_dates(text: str) -> tuple[list[tuple[str, set[tuple[int, int]]]], str]:
    """Return each date found as (original text, possible (month, day) readings), plus the text with dates removed."""
    found = []
    for kind, pattern in _DATE_PATTERNS:
        def take(m: re.Match, kind: str = kind) -> str:
            if kind in ("day_range_month", "month_day_range"):
                month, first, last = ((m.group(3), m.group(1), m.group(2)) if kind == "day_range_month"
                                      else (m.group(1), m.group(2), m.group(3)))
                month_number = _MONTHS[month[:3].lower()]
                for day in (first, last):
                    if _valid(month_number, int(day)):
                        found.append((f"{day} {month}", {(month_number, int(day))}))
                return " "
            if kind == "iso":
                readings = {(int(m.group(1)), int(m.group(2)))}
            elif kind == "month_day":
                readings = {(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)))}
            elif kind == "day_month":
                readings = {(_MONTHS[m.group(2)[:3].lower()], int(m.group(1)))}
            else:
                a, b = int(m.group(1)), int(m.group(2))
                readings = {(a, b), (b, a)}
            readings = {r for r in readings if _valid(*r)}
            if readings:
                found.append((m.group(0).strip(), readings))
            return " "
        text = pattern.sub(take, text)
    return found, _TIME.sub(" ", text)


def find_numbers(text: str, include_small: bool = False) -> list[tuple[str, float]]:
    """Numbers in text that has already had dates removed, as (original text, value).

    Bare small integers are skipped in generated text, but kept (include_small) when reading the notes,
    so "10% complete" in the output can match a bare "10" in a CSV column."""
    found = []
    for m in _NUMBER.finditer(text):
        currency, whole, decimals, suffix = m.groups()
        value = float(whole.replace(",", "") + (f".{decimals}" if decimals else ""))
        if not include_small and not (currency or decimals or suffix) and value <= _IGNORE_BARE_INTS_UP_TO:
            continue
        if suffix and suffix.lower() in _MULTIPLIERS:
            value *= _MULTIPLIERS[suffix.lower()]
        found.append((m.group(0).strip(), value))
    return found


def _close(value: float, allowed: set[float]) -> bool:
    for a in allowed:
        if abs(value - a) <= 0.015 * abs(a) or value in (round(a), round(a, 1)):
            return True
    return False


def unsupported_figures(texts: list[str], sources: list[str]) -> list[str]:
    allowed_dates: set[tuple[int, int]] = set()
    allowed_numbers: set[float] = set()
    for source in sources:
        dates, rest = find_dates(source)
        for _, readings in dates:
            allowed_dates |= readings
        allowed_numbers |= {v for _, v in find_numbers(rest, include_small=True)}

    problems = []
    for text in texts:
        dates, rest = find_dates(text)
        problems += [f'Date "{raw}" isn\'t in the notes' for raw, readings in dates if not readings & allowed_dates]
        problems += [f'Figure "{raw}" isn\'t in the notes' for raw, value in find_numbers(rest)
                     if not _close(value, allowed_numbers)]
    return problems


# --- Invented attributions ------------------------------------------------------------------
# "Steering must approve the overtime" when the notes only say "need approval" is exactly the kind of
# detail an executive acts on, so who decides is checked like figures are.

_ROLE = re.compile(r"\b(steering(?: committee)?|steerco|sponsors?|board|executive committee|cfo|ceo|cio|coo|cto|"
                   r"vp|vice president|directors?|finance committee|pmo)\b", re.IGNORECASE)
# Capitals after a letter, digit, comma or bracket: after ";" or ":" a capital starts a clause, not a name.
_MID_SENTENCE_NAME = re.compile(r"(?<=[a-z0-9,)] )[A-Z][a-z]{2,}")
# Same body, different names: "steering committee" in a summary is fine when the notes say "steerco".
_ROLE_ALIASES = {"steering": ("steering", "steerco", "steering committee"),
                 "steerco": ("steering", "steerco", "steering committee"),
                 "steering committee": ("steering", "steerco", "steering committee")}


def _mentions(text: str, role: str) -> bool:
    return any(alias in text for alias in _ROLE_ALIASES.get(role, (role,)))
_NOT_NAMES = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
              "Red", "Amber", "Green", "Unknown", "Schedule", "Budget", "Scope", "Risk", "Overall", "Leadership"}
_TOPIC_WORD = re.compile(r"[a-z0-9]{5,}")
_GOVERNANCE_WORDS = {"approval", "approve", "approves", "decision", "decide", "steering", "committee", "needed",
                     "required", "leadership", "sponsor"}
_ID = re.compile(r"\b[a-z]{1,10}-?\d+\b")


def _topic(text: str) -> tuple[set[str], set[str]]:
    lowered = text.lower()
    return (set(_TOPIC_WORD.findall(lowered)) - _GOVERNANCE_WORDS,
            {i.replace("-", "") for i in _ID.findall(lowered)})


def _covers(sentence: str, ask: str) -> bool:
    s_words, s_ids = _topic(sentence)
    a_words, a_ids = _topic(ask)
    return bool(s_ids & a_ids) or len(s_words & a_words) >= 2


_CLAUSE_SPLIT = re.compile(r"[,;]|\band\b", re.IGNORECASE)
_OWN_APPROVAL = re.compile(r"\b(approval|approve[sd]?|decide|decision|needed|required|sign-off|must)\b",
                           re.IGNORECASE)


def _governed_text(sentence: str, start: int) -> str:
    """The part of the sentence a role at `start` applies to: its own clause, plus following clauses joined by
    "and" or commas, until one brings its own approval phrase ("..., and approval is needed for X")."""
    clauses = _CLAUSE_SPLIT.split(sentence[start:])
    governed = [clauses[0]]
    for clause in clauses[1:]:
        if _OWN_APPROVAL.search(clause):
            break
        governed.append(clause)
    before = _CLAUSE_SPLIT.split(sentence[:start])[-1]  # "CR-14 needs steering approval": objects come first
    return before + " " + " ".join(governed)


def unsupported_attributions(summary: str, asks: list[str], notes: str) -> list[str]:
    """Approvers named in the summary must be the ones the notes give for that ask; names must be in the notes."""
    lowered_notes = notes.lower()
    note_words = set(re.findall(r"[a-z]{4,}", lowered_notes))
    problems = []
    for sentence in _SENTENCE_RE.split(summary):
        for name in _MID_SENTENCE_NAME.findall(sentence):
            lowered = name.lower()
            # "Executive" from "exec": a word the notes abbreviate isn't an invented name.
            if (name not in _NOT_NAMES and lowered not in lowered_notes
                    and not any(lowered.startswith(w) for w in note_words)):
                problems.append(f'Name "{name}" isn\'t in the notes')
        for match in _ROLE.finditer(sentence):
            role = match.group(0).lower()
            if not _mentions(lowered_notes, role):
                problems.append(f'"{role}" isn\'t named in the notes')
                continue
            governed = _governed_text(sentence, match.start())
            for ask in asks:
                if _covers(governed, ask) and not _mentions(ask.lower(), role):
                    problems.append(f'Says "{role}" for "{ask}", but the notes don\'t say who approves that')
    return list(dict.fromkeys(problems))


def ground_facts(facts: Facts, notes: str) -> tuple[Facts, list[str]]:
    """Enforce "never infer" for the facts the rules depend on: drop any extracted date or budget figure
    that doesn't appear in the notes. Returns the cleaned facts and what was dropped."""
    found, rest = find_dates(notes)
    note_dates = {r for _, readings in found for r in readings}
    note_numbers = {v for _, v in find_numbers(rest, include_small=True)}
    dropped: list[str] = []

    def keep_date(d: date | None, what: str) -> date | None:
        if d is None or (d.month, d.day) in note_dates:
            return d
        dropped.append(f"{what}: {d.isoformat()}")
        return None

    def keep_number(v: float | None, what: str) -> float | None:
        if v is None or _close(v, note_numbers):
            return v
        dropped.append(f"{what}: {v:g}")
        return None

    milestones = None if facts.milestones is None else [
        replace(m,
                planned_date=keep_date(m.planned_date, f"{m.name} planned date"),
                forecast_date=keep_date(m.forecast_date, f"{m.name} forecast date"),
                actual_date=keep_date(m.actual_date, f"{m.name} actual date"))
        for m in facts.milestones
    ]
    budget = facts.budget and replace(
        facts.budget,
        planned=keep_number(facts.budget.planned, "budget planned"),
        actual=keep_number(facts.budget.actual, "budget actual"),
        forecast=keep_number(facts.budget.forecast, "budget forecast"),
        unforecast_costs=[replace(c, amount=keep_number(c.amount, f"{c.description} amount"))
                          for c in facts.budget.unforecast_costs],
    )
    as_of = keep_date(facts.as_of_date, "report date")
    return replace(facts, milestones=milestones, budget=budget, as_of_date=as_of), dropped


# --- Summary shape --------------------------------------------------------------------------
# Style, not correctness: a break triggers a rewrite but never a warning.
# The full summary is the model's headline plus code-built sentences (red items, amber items, what the
# notes don't cover, decisions needed), so it can run to five sentences.

SUMMARY_MAX_WORDS = 120
SUMMARY_MAX_SENTENCES = 5
HEADLINE_MAX_WORDS = 30
SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z])")  # "98.7%" and "$1.2M" don't end a sentence
_LEADERSHIP = re.compile(r"\b(leadership|steering|sponsor|executives?)\b", re.IGNORECASE)


_CONTENT_WORD = re.compile(r"[a-z0-9]{4,}")


def headline_style_problems(headline: str, has_asks: bool, facts_paragraph: str = "") -> list[str]:
    """What the pipeline checks before accepting the model's one sentence."""
    problems = []
    words = set(_CONTENT_WORD.findall(headline.lower()))
    if words and len(words & set(_CONTENT_WORD.findall(facts_paragraph.lower()))) / len(words) >= 0.7:
        problems.append("The sentence repeats the facts that follow it; give the one-line takeaway instead, "
                        "in different words")
    if SENTENCE_END.search(headline):
        problems.append("Write exactly one sentence")
    words = len(headline.split())
    if words > HEADLINE_MAX_WORDS:
        problems.append(f"The sentence is {words} words; keep it to {HEADLINE_MAX_WORDS}")
    colours = sorted({m.group(1).lower() for m in _COLOR_RE.finditer(headline)})
    if colours:
        problems.append(f"The sentence names status colours ({', '.join(colours)}); describe the problem instead")
    if not has_asks and _LEADERSHIP.search(headline):
        problems.append("The sentence suggests a leadership action, but there are no asks")
    return problems


def summary_style_problems(summary: str, statuses: dict[str, str], low_confidence: bool, has_asks: bool) -> list[str]:
    problems = []
    words = len(summary.split())
    if words > SUMMARY_MAX_WORDS:
        problems.append(f"The summary is {words} words; keep it under {SUMMARY_MAX_WORDS}")
    sentences = len(SENTENCE_END.findall(summary)) + 1
    if sentences > SUMMARY_MAX_SENTENCES:
        problems.append(f"The summary is {sentences} sentences; use at most {SUMMARY_MAX_SENTENCES}")
    for dim, status in statuses.items():
        mentioned = DIMENSION_WORDS[dim].search(summary)
        if status == "unknown" and not mentioned:
            problems.append(f"The summary doesn't say the notes don't cover {dim}")
        if status in ("amber", "red") and not mentioned:
            problems.append(f"The summary doesn't cover what's behind the {dim} problem")
    # The page shows every status with an icon right above the summary, so colours in the prose are clutter.
    colours = sorted({m.group(1).lower() for m in _COLOR_RE.finditer(summary)})
    if colours:
        problems.append(f"The summary names status colours ({', '.join(colours)}); describe the problems instead")
    if low_confidence and "confidence" not in summary.lower():
        problems.append("The summary doesn't say the status is low-confidence")
    if not has_asks and _LEADERSHIP.search(summary):
        problems.append("The summary suggests a leadership action, but there are no asks")
    return problems


# Linking words that turn two true facts into an invented cause and effect ("slipped, creating a collision").
# The writer is told not to, but kept doing it, so a linking word the notes don't use earns a rewrite.
_CONNECTIVE = re.compile(
    r"\b(creat(?:ing|es)|caus(?:ing|es)|lead(?:ing|s) to|threaten(?:s|ing)?|block(?:ing|s)|to avoid|so that|"
    r"due to|because|as a result|driven by|result(?:ing|s) in|delaying|jeopardi[sz]\w*|putting \w+ at risk|"
    r"to prevent|prevent(?:s|ing)|avert\w*)\b",
    re.IGNORECASE,
)


def invented_connectives(summary: str, notes: str) -> list[str]:
    lowered_notes = notes.lower()
    found = {m.group(0).lower() for m in _CONNECTIVE.finditer(summary)}
    return [f'The summary links facts with "{c}", which the notes don\'t; state the facts side by side instead'
            for c in sorted(found) if c not in lowered_notes]


def check_texts(texts: list[str], notes: str, card: Scorecard) -> list[str]:
    reasons = [d.reason for d in card.dimensions] + [card.overall_reason]
    problems = find_contradictions(texts, card) + unsupported_figures(texts, [notes, *reasons])
    return list(dict.fromkeys(problems))
