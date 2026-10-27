"""Step 4: check the generated text in code before it reaches the reader.

- Shape: the summary tool output matches the expected structure.
- Status: any status color the text mentions matches the computed status.
- Figures: every number and date in the text appears in the notes or in a rule's reason.

The figure check is deliberately conservative. It normalises formats (2.4M = $2,400,000,
4/24 = 24 April) and allows rounding, but anything it can't trace back to the input is flagged.
"""

import re
from typing import Any

from .rules import Scorecard, Status
from .schema import SchemaError

MAX_SUMMARY_CHARS = 1200


def parse_summary(data: Any) -> str:
    if not isinstance(data, dict) or set(data) - {"executive_summary"}:
        raise SchemaError("expected an object with only executive_summary")
    summary = data.get("executive_summary")
    if not isinstance(summary, str) or not summary.strip():
        raise SchemaError("executive_summary must be a non-empty string")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise SchemaError(f"executive_summary is longer than {MAX_SUMMARY_CHARS} characters")
    if "<" in summary and ">" in summary:
        raise SchemaError("executive_summary contains markup")
    return summary.strip()


# --- Status contradictions ----------------------------------------------------------------

_COLORS = {"green": Status.GREEN, "amber": Status.AMBER, "yellow": Status.AMBER, "red": Status.RED}
_COLOR_RE = re.compile(r"\b(green|amber|yellow|red)\b", re.IGNORECASE)
DIMENSION_WORDS = {
    dim: re.compile(pattern, re.IGNORECASE)
    for dim, pattern in {
        "schedule": r"\b(schedul|timeline|milestone|dates?\b|deadline|go-live|cutover|launch)",
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


def check_texts(texts: list[str], notes: str, card: Scorecard) -> list[str]:
    reasons = [d.reason for d in card.dimensions] + [card.overall_reason]
    problems = find_contradictions(texts, card) + unsupported_figures(texts, [notes, *reasons])
    return list(dict.fromkeys(problems))
