"""Deterministic parsing of comma-separated tables pasted into the notes: task exports, budget tables and
change-request tables.

A model reading a CSV by eye drops rows, misreads columns and can't be trusted to add up a budget, and
the grounding check (validate.ground_facts) rightly drops any total that isn't written in the notes. So
tables are parsed here, totals are computed here, and the results replace what extraction returned for
those fields. The model still reads everything else (free-text notes, risks, asks).
"""

import csv
import io
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from .schema import Budget, Facts, Milestone, ScopeChange


@dataclass(frozen=True)
class Task:
    name: str
    planned: date | None
    forecast: date | None
    actual: date | None
    complete: bool
    critical: bool | None


@dataclass
class ParsedTables:
    tasks: list[Task] = field(default_factory=list)
    budget: Budget | None = None
    scope_changes: list[ScopeChange] | None = None


# --- Cells -------------------------------------------------------------------------------------


def parse_number(cell: str) -> float | None:
    """'$1,234', '-4000', '(4,000)', '62k', '1.2M' -> number; anything else -> None."""
    text = cell.strip().replace("$", "").replace("€", "").replace("£", "").replace(",", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([kKmM]?)", text)
    if not m:
        return None
    value = float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]
    return -value if negative else value


def parse_date(cell: str) -> date | None:
    text = cell.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _yes(cell: str) -> bool | None:
    text = cell.strip().lower()
    if text in ("y", "yes", "true", "critical", "x"):
        return True
    if text in ("n", "no", "false"):
        return False
    return None


# --- Blocks --------------------------------------------------------------------------------------


def _blocks(notes: str) -> list[list[list[str]]]:
    """Runs of consecutive lines that parse as CSV rows with the same number of columns (at least 3)."""
    blocks, current = [], []
    for line in notes.splitlines():
        row = next(csv.reader(io.StringIO(line)), []) if line.count(",") >= 2 else []
        if len(row) >= 3 and (not current or len(row) == len(current[0])):
            current.append([c.strip() for c in row])
            continue
        if len(current) >= 2:
            blocks.append(current)
        current = [[c.strip() for c in row]] if len(row) >= 3 else []
    if len(current) >= 2:
        blocks.append(current)
    return blocks


def _column(header: list[str], *patterns: str) -> int | None:
    for pattern in patterns:
        for i, name in enumerate(header):
            if re.search(pattern, name.lower()):
                return i
    return None


def _cell(row: list[str], i: int | None) -> str:
    return row[i] if i is not None and i < len(row) else ""


# --- Table types ---------------------------------------------------------------------------------


def _tasks(header: list[str], rows: list[list[str]]) -> list[Task] | None:
    name = _column(header, r"^(task|task name|name|milestone|activity|deliverable)$", r"task|milestone|name")
    planned = _column(header, r"(planned|baseline|target).*(finish|end|date)", r"^(planned|baseline|due|finish)")
    if name is None or planned is None:
        return None
    forecast = _column(header, r"forecast.*(finish|end|date)", r"^forecast")
    actual = _column(header, r"actual.*(finish|end|date)", r"^actual")
    status = _column(header, r"^status$")
    pct = _column(header, r"%|percent")
    critical = _column(header, r"critical")
    tasks = []
    for row in rows:
        planned_date = parse_date(_cell(row, planned))
        task_name = _cell(row, name)
        if not task_name or planned_date is None:
            continue  # summary rows like "BUDGET SUMMARY,,,,..." have no dates
        forecast_date = parse_date(_cell(row, forecast))
        actual_date = parse_date(_cell(row, actual))
        done = (bool(re.search(r"complete|done|closed|finished", _cell(row, status).lower()))
                and "not" not in _cell(row, status).lower()) or parse_number(_cell(row, pct)) == 100
        if done and actual_date is None:
            actual_date = forecast_date or planned_date
        tasks.append(Task(task_name, planned_date, forecast_date, actual_date if done else None, done,
                          _yes(_cell(row, critical))))
    return tasks or None


def _budget(header: list[str], rows: list[list[str]]) -> Budget | None:
    planned = _column(header, r"^(planned|plan|budget|approved|baseline)", r"planned|approved|budget")
    forecast = _column(header, r"forecast|estimate at completion|^eac")
    actual = _column(header, r"^(actual|spent|spend)")
    if planned is None or (forecast is None and actual is None) or planned in (forecast, actual):
        return None
    if _column(header, r"finish|date") is not None:
        return None  # a task table that happens to have a "planned" column

    def total(column: int | None) -> float | None:
        if column is None:
            return None
        totals = [r for r in rows if re.search(r"\btotal\b", r[0].lower())]
        values = [parse_number(_cell(r, column)) for r in (totals[:1] or rows)]
        values = [v for v in values if v is not None]
        return sum(values) if values else None

    budget = Budget(planned=total(planned), forecast=total(forecast), actual=total(actual))
    return budget if budget.planned is not None else None


def _change_requests(header: list[str], rows: list[list[str]]) -> list[ScopeChange] | None:
    ident = _column(header, r"^(cr|cr id|cr #|change|change id|id)$")
    status = _column(header, r"^status$")
    description = _column(header, r"description|summary|title|change request")
    if ident is None or status is None or description is None:
        return None
    impacts = _column(header, r"impacts|affect")
    cost = _column(header, r"cost")
    schedule = _column(header, r"schedule|days|weeks")
    changes = []
    for row in rows:
        cr_id, text = _cell(row, ident), _cell(row, description)
        if not cr_id or not text:
            continue
        raw_status = _cell(row, status).lower()
        state = ("rejected" if "reject" in raw_status else
                 "pending" if re.search(r"pending|submitted|proposed|await|review|open", raw_status) else
                 "approved" if "approv" in raw_status else None)
        changes.append(ScopeChange(
            description=f"{cr_id}: {text}",
            status=state,
            affected_milestone=_cell(row, impacts) or None,
            impact_estimate=_cell(row, schedule) or None,
            # Whole description when it's short enough to read in a sentence; cut on a word otherwise.
            title=f"{cr_id}: {text}" if len(text) <= 60 else f"{cr_id}: {' '.join(text.split()[:8])}…",
            cost=parse_number(_cell(row, cost)),
        ))
    return changes or None


def parse_tables(notes: str) -> ParsedTables:
    parsed = ParsedTables()
    for header, *rows in _blocks(notes):
        if parsed.scope_changes is None and (changes := _change_requests(header, rows)):
            parsed.scope_changes = changes
        elif not parsed.tasks and (tasks := _tasks(header, rows)):
            parsed.tasks = tasks
        elif parsed.budget is None and (budget := _budget(header, rows)):
            parsed.budget = budget
    return parsed


# --- Applying them -------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]{3,}")


def _mentions_task(text: str, task: Task) -> bool:
    words = set(_WORD.findall(task.name.lower()))
    return bool(words) and len(words & set(_WORD.findall(text.lower()))) / len(words) >= 0.6


def apply_tables(facts: Facts, parsed: ParsedTables, notes: str, accomplishment_days: int,
                 next_step_days: int) -> Facts:
    """Replace what extraction read from tables with what code parsed, and derive this period's
    accomplishments and next steps from task dates."""
    changes: dict = {}
    if parsed.budget:
        currency = facts.budget.currency if facts.budget and facts.budget.currency else ("$" if "$" in notes else None)
        unforecast = facts.budget.unforecast_costs if facts.budget else []
        changes["budget"] = replace(parsed.budget, currency=currency, unforecast_costs=unforecast)
    if parsed.scope_changes is not None:
        changes["scope_changes"] = parsed.scope_changes
    if parsed.tasks:
        tasks = parsed.tasks
        changes["milestones"] = [Milestone(t.name, t.planned, t.forecast, t.actual, t.critical) for t in tasks]
        as_of = facts.as_of_date
        # Free-text items that aren't just a task restated are kept; task items come from the dates.
        free_done = [a for a in facts.accomplishments if not any(_mentions_task(a, t) for t in tasks)]
        free_next = [s for s in facts.next_steps if not any(_mentions_task(s, t) for t in tasks)]
        done, upcoming = [], []
        if as_of:
            start = as_of - timedelta(days=accomplishment_days)
            done = [t.name for t in tasks if t.complete and t.actual and start <= t.actual <= as_of]  # inclusive
            horizon = as_of + timedelta(days=next_step_days)
            due = sorted(((t.forecast or t.planned), t.name) for t in tasks
                         if not t.complete and as_of <= (t.forecast or t.planned) <= horizon)
            upcoming = [f"{name} (due {when.isoformat()})" for when, name in due]
        changes["accomplishments"] = done + free_done
        changes["next_steps"] = upcoming + free_next
    return replace(facts, **changes) if changes else facts
