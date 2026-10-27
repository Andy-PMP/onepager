"""Deterministic status rules. No LLM here: each rule is a pure function of the extracted facts.

Every rule returns the status, an id for the branch that fired, a plain-language reason (shown
in the "How status was decided" panel), any gaps it found in the data, and a plain clause for the
executive summary. Gaps and clauses are full sentences that name items by their short titles.
"""

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from .schema import Budget, Facts, Milestone, Risk, ScopeChange

THRESHOLDS_PATH = Path(__file__).with_name("thresholds.toml")


class Status(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    UNKNOWN = "unknown"


_SEVERITY = {Status.GREEN: 0, Status.AMBER: 1, Status.RED: 2}


@dataclass(frozen=True)
class Thresholds:
    critical_slip_red_days: int = 14
    green_max_overrun_pct: float = 5
    amber_max_overrun_pct: float = 10
    high_impact_levels: tuple[str, ...] = ("high",)
    low_confidence_unknown_count: int = 2
    accomplishment_window_days: int = 14
    next_steps_window_days: int = 30


@cache
def load_thresholds(path: Path = THRESHOLDS_PATH) -> Thresholds:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return Thresholds(
        critical_slip_red_days=raw["schedule"]["critical_slip_red_days"],
        green_max_overrun_pct=raw["budget"]["green_max_overrun_pct"],
        amber_max_overrun_pct=raw["budget"]["amber_max_overrun_pct"],
        high_impact_levels=tuple(raw["risk"]["high_impact_levels"]),
        low_confidence_unknown_count=raw["overall"]["low_confidence_unknown_count"],
        accomplishment_window_days=raw["report"]["accomplishment_window_days"],
        next_steps_window_days=raw["report"]["next_steps_window_days"],
    )


@dataclass(frozen=True)
class RuleResult:
    dimension: str
    status: Status
    rule: str
    reason: str
    gaps: list[str] = field(default_factory=list)
    # A plain clause for the executive summary ("Cutover slipped 21 days to 2026-12-11"). Written by code
    # from the same facts as the reason, so it can't invent links between them. Empty when unknown.
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status.value,
            "rule": self.rule,
            "reason": self.reason,
            "gaps": list(self.gaps),
        }


# --- Wording helpers ------------------------------------------------------------------------------


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """plural(1, "item") -> "1 item"; plural(2, "item") -> "2 items"."""
    return f"{n} {singular if n == 1 else (plural_form or singular + 's')}"


def _and(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _short(text: str, limit: int = 80) -> str:
    """Trim a description so a reason or gap stays one line."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _label(item: Risk | ScopeChange) -> str:
    """The short title when extraction gave one, else the description cut to fit."""
    return item.title or _short(item.description)


def _q(name: str) -> str:
    return f"'{name}'"


# An estimate means an amount, a duration or a date. Naming the phase a change affects isn't one,
# and the model kept counting that, so code makes the call.
_ESTIMATE = re.compile(
    r"[$€£]\s?\d|\b\d[\d,.]*\s?(k|m|bn|million|thousand|days?|weeks?|wks?|months?)\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_NO_IMPACT = re.compile(r"^\s*[+-]?0\s*(days?|weeks?)?\s*$", re.IGNORECASE)


def has_estimate(text: str | None) -> bool:
    return bool(text and _ESTIMATE.search(text))


def money(value: float, currency: str | None) -> str:
    amount = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    if not currency:
        return amount
    # Symbols go in front ($2,400,000); codes go after (2,400,000 USD).
    return f"{currency}{amount}" if len(currency) == 1 else f"{amount} {currency}"


def _money(value: float, b: Budget) -> str:
    return money(value, b.currency)


# --- Schedule -----------------------------------------------------------------------------


def _slip_days(m: Milestone) -> int | None:
    latest = m.actual_date or m.forecast_date
    if m.planned_date is None or latest is None:
        return None
    return (latest - m.planned_date).days


def _is_missed(m: Milestone, as_of: date | None) -> bool:
    """Planned date has passed, the milestone isn't done, and nobody has given a new date."""
    return (
        as_of is not None
        and m.planned_date is not None
        and m.planned_date < as_of
        and m.actual_date is None
        and m.forecast_date is None
    )


def _slip_clause(m: Milestone, days: int) -> str:
    n = plural(days, "day")
    if m.actual_date:
        return f"{m.name} finished {n} late, on {m.actual_date.isoformat()}"
    return f"{m.name} slipped {n} to {m.forecast_date.isoformat()}"  # "slipped" reads right for plural names too


def score_schedule(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "schedule"
    milestones = facts.milestones
    if not milestones:
        return RuleResult(dim, Status.UNKNOWN, "schedule.no_milestones",
                          "The notes don't list any milestones.", ["No milestones or dates are given."])
    dated = [m for m in milestones if m.planned_date is not None]
    if not dated:
        return RuleResult(dim, Status.UNKNOWN, "schedule.no_dates",
                          "Milestones are named but none has a planned date.",
                          [f"{_q(m.name)} has no date." for m in milestones])

    gaps: list[str] = []
    if facts.as_of_date is None:
        gaps.append("There's no report date, so missed milestones can't be detected.")
    gaps += [f"{_q(m.name)} has no date." for m in milestones
             if not (m.planned_date or m.forecast_date or m.actual_date)]
    unrated = [_q(m.name) for m in dated
               if (_slip_days(m) or 0) > t.critical_slip_red_days and m.is_critical is None]
    if unrated:
        gaps.append(f"It isn't stated whether {_and(unrated)} {'is' if len(unrated) == 1 else 'are'} critical.")

    critical_slips = [(m, d) for m in dated if m.is_critical and (d := _slip_days(m)) is not None
                      and d > t.critical_slip_red_days]
    if critical_slips:
        m, d = max(critical_slips, key=lambda x: x[1])
        return RuleResult(dim, Status.RED, "schedule.critical_slip",
                          f"Critical milestone {_q(m.name)} has slipped {plural(d, 'day')} "
                          f"(more than {t.critical_slip_red_days}).", gaps,
                          summary=_slip_clause(m, d))

    missed = [m for m in dated if _is_missed(m, facts.as_of_date)]
    unplanned = [m for m in missed if not m.recovery_plan]
    if unplanned:
        m = unplanned[0]
        return RuleResult(dim, Status.RED, "schedule.missed_no_recovery",
                          f"{_q(m.name)} was due {m.planned_date.isoformat()}, "
                          "isn't done, and has no new date or recovery plan.", gaps,
                          summary=f"{m.name} missed its {m.planned_date.isoformat()} date and has no new date "
                                  "or recovery plan")

    slips = [(m, d) for m in dated if (d := _slip_days(m)) is not None and d > 0]
    if slips:
        m, d = max(slips, key=lambda x: x[1])
        label = {True: "critical milestone", False: "non-critical milestone", None: "milestone"}[m.is_critical]
        extra = f" ({len(slips)} milestones slipped in total)" if len(slips) > 1 else ""
        others = len(slips) - 1
        return RuleResult(dim, Status.AMBER, "schedule.slip",
                          f"Largest slip: {label} {_q(m.name)}, {plural(d, 'day')}{extra}.", gaps,
                          summary=_slip_clause(m, d) + (f" ({plural(others, 'other milestone')} also slipped)"
                                                        if others else ""))
    if missed:
        m = missed[0]
        return RuleResult(dim, Status.AMBER, "schedule.missed_with_recovery",
                          f"{_q(m.name)} missed its date but has a recovery plan.", gaps,
                          summary=f"{m.name} missed its {m.planned_date.isoformat()} date; a recovery plan is "
                                  "in place")

    return RuleResult(dim, Status.GREEN, "schedule.on_track",
                      f"No slips across {plural(len(dated), 'dated milestone')}.", gaps,
                      summary="the schedule is on track")


# --- Budget -------------------------------------------------------------------------------


def _unforecast_gaps(b: Budget, compare: float, label: str) -> list[str]:
    """Known costs the forecast leaves out. Reported with the adjusted figure; the status stays on the forecast."""
    priced = [c for c in b.unforecast_costs if c.amount is not None]
    unpriced = [c.description for c in b.unforecast_costs if c.amount is None]
    gaps = []
    if priced:
        extra = sum(c.amount for c in priced)
        adjusted = compare + extra
        pct = (adjusted - b.planned) / b.planned * 100
        what = "; ".join(_short(c.description) for c in priced)
        gaps.append(f"The {label} excludes {_money(extra, b)} of known costs ({what}). "
                    f"Including them: {_money(adjusted, b)} vs plan {_money(b.planned, b)} ({pct:+.1f}%).")
    if unpriced:
        gaps.append(f"{_and([_q(_short(u)) for u in unpriced])} {'isn' if len(unpriced) == 1 else 'aren'}'t in "
                    f"the {label}, and no amount is given.")
    return gaps


def score_budget(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "budget"
    b = facts.budget
    if b is None or b.planned is None:
        return RuleResult(dim, Status.UNKNOWN, "budget.no_plan",
                          "No planned budget figure in the notes.", ["No budget figures are given."])
    if b.planned <= 0:
        return RuleResult(dim, Status.UNKNOWN, "budget.invalid_plan",
                          "The planned budget isn't a positive number.", ["The planned budget figure is unclear."])
    compare, label = (b.forecast, "forecast") if b.forecast is not None else (b.actual, "actual")
    if compare is None:
        return RuleResult(dim, Status.UNKNOWN, "budget.no_actuals",
                          "A planned budget is given but no actual or forecast spend.",
                          ["There's no actual or forecast spend against the budget."])

    overrun = (compare - b.planned) / b.planned * 100
    detail = f"{label.capitalize()} {_money(compare, b)} vs plan {_money(b.planned, b)} ({overrun:+.1f}%)."
    gaps = [] if b.forecast is not None else ["There's no forecast at completion, so actual spend to date was used."]
    gaps += _unforecast_gaps(b, compare, label)
    clause = (f"the budget {'forecast' if label == 'forecast' else 'spend to date'} is {_money(compare, b)} "
              f"against a {_money(b.planned, b)} plan ({overrun:+.1f}%)")
    if overrun <= t.green_max_overrun_pct:
        return RuleResult(dim, Status.GREEN, "budget.within_tolerance", detail, gaps, summary=clause)
    if overrun <= t.amber_max_overrun_pct:
        return RuleResult(dim, Status.AMBER, "budget.minor_overrun", detail, gaps, summary=clause)
    return RuleResult(dim, Status.RED, "budget.major_overrun", detail, gaps, summary=clause)


# --- Scope --------------------------------------------------------------------------------


def affected_milestones(c: ScopeChange) -> list[str]:
    """'Construction substantially complete; Move weekend' -> both names."""
    return [x.strip() for x in re.split(r";|\band\b", c.affected_milestone or "") if x.strip()]


def if_approved(c: ScopeChange, currency: str | None) -> str:
    """'if approved, it adds +3 weeks and $62,000', from whatever estimate the change carries."""
    parts = []
    if has_estimate(c.impact_estimate) and not _NO_IMPACT.match(c.impact_estimate or ""):
        parts.append(c.impact_estimate.strip())
    if c.cost and not re.search(r"[$€£]", " ".join(parts)):  # don't repeat an amount the estimate already gives
        parts.append(money(c.cost, currency))
    return f"if approved, it adds {_and(parts)}" if parts else ""


def score_scope(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "scope"
    changes = facts.scope_changes
    if changes is None:
        return RuleResult(dim, Status.UNKNOWN, "scope.not_mentioned",
                          "The notes don't say whether scope changed.", ["There's no information on scope changes."])

    critical = {m.name.casefold(): m.name for m in facts.milestones or [] if m.is_critical}
    # Rejected changes are closed; anything else not yet approved is still pending.
    pending = [c for c in changes if c.status not in ("approved", "rejected")]
    currency = facts.budget.currency if facts.budget else None
    gaps = []
    if any(c.status is None for c in changes):
        gaps.append("Approval status isn't stated for some scope changes.")
    gaps += [f"{_q(_label(c))} has no cost or schedule estimate." for c in pending
             if not has_estimate(c.impact_estimate) and not c.cost]
    b = facts.budget
    base = (b.forecast if b and b.forecast is not None else b.actual if b else None)
    for c in pending:
        if c.cost and b and b.planned and base is not None:
            adjusted = base + c.cost
            pct = (adjusted - b.planned) / b.planned * 100
            gaps.append(f"If {_q(_label(c))} is approved, its estimated {money(c.cost, currency)} would take the "
                        f"forecast to {money(adjusted, currency)} vs plan {money(b.planned, currency)} "
                        f"({pct:+.1f}%).")

    hits = [(c, [critical[a.casefold()] for a in affected_milestones(c) if a.casefold() in critical])
            for c in pending]
    hits = [(c, names) for c, names in hits if names]
    if hits:
        c, names = hits[0]
        noun = "critical milestone" if len(names) == 1 else "critical milestones"
        impact = if_approved(c, currency)
        return RuleResult(dim, Status.RED, "scope.unapproved_critical",
                          f"Unapproved change {_q(_label(c))} affects {noun} {_and([_q(n) for n in names])}.", gaps,
                          summary=f"pending scope change {_q(_label(c))} would affect {noun} "
                                  f"{_and([_q(n) for n in names])}" + (f"; {impact}" if impact else ""))
    if pending:
        n = len(pending)
        items = []
        for c in pending:
            impact = if_approved(c, currency)
            items.append(_q(_label(c)) + (f" ({impact})" if impact else ""))
        return RuleResult(dim, Status.AMBER, "scope.pending_changes",
                          f"{plural(n, 'change request')} pending approval.", gaps,
                          summary=f"{plural(n, 'change request')} {'awaits' if n == 1 else 'await'} approval: "
                                  f"{_and(items)}")
    if changes:
        return RuleResult(dim, Status.GREEN, "scope.all_resolved",
                          f"All {plural(len(changes), 'scope change')} approved or rejected.", gaps,
                          summary="all scope changes are resolved")
    return RuleResult(dim, Status.GREEN, "scope.no_changes", "No scope changes reported.", gaps,
                      summary="scope is unchanged")


# --- Risk ---------------------------------------------------------------------------------


def score_risk(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "risk"
    risks = facts.risks
    if risks is None:
        return RuleResult(dim, Status.UNKNOWN, "risk.not_mentioned",
                          "The notes don't mention risks or issues.", ["No risks or issues are listed."])

    open_risks = [r for r in risks if r.state != "closed"]
    high = [r for r in open_risks if r.impact in t.high_impact_levels]
    # An item with no stated impact is unknown, not "not high-impact": it could be the worst one.
    unrated = [r for r in open_risks if r.impact is None]
    gaps = [f"{_q(_label(r))} has no stated impact." for r in unrated]
    if open_risks and len(unrated) == len(open_risks):
        n = len(open_risks)
        reason = "The one open item has no stated impact." if n == 1 else \
            f"None of the {n} open items has a stated impact."
        return RuleResult(dim, Status.UNKNOWN, "risk.unrated", reason, gaps)
    gaps += [f"{_q(_label(r))} has no target date for resolution." for r in high if not r.resolve_by]

    uncovered = [r for r in high if not r.owner or not r.mitigation]
    if uncovered:
        r = uncovered[0]
        missing = " and ".join(x for x, v in (("owner", r.owner), ("mitigation", r.mitigation)) if not v)
        extra = f" ({len(uncovered)} such items)" if len(uncovered) > 1 else ""
        others = len(uncovered) - 1
        return RuleResult(dim, Status.RED, "risk.high_unmanaged",
                          f"High-impact {r.kind or 'risk'} {_q(_label(r))} has no {missing}{extra}.",
                          gaps,
                          summary=f"high-impact {r.kind or 'risk'} {_q(_label(r))} has no {missing}"
                                  + (f" ({plural(others, 'more high-impact item')} "
                                     f"{'lacks' if others == 1 else 'lack'} an owner or mitigation)"
                                     if others else ""))
    if high:
        n = len(high)
        return RuleResult(dim, Status.AMBER, "risk.high_managed",
                          f"{plural(n, 'open high-impact item')}, {'each ' if n != 1 else ''}with an owner "
                          "and mitigation.",
                          gaps,
                          summary=f"{plural(n, 'high-impact risk or issue', 'high-impact risks or issues')} "
                                  f"{'is' if n == 1 else 'are'} open ({_and([_q(_label(r)) for r in high])}), "
                                  f"{'each ' if n != 1 else ''}with an owner and mitigation")
    if open_risks:
        n = len(open_risks)
        return RuleResult(dim, Status.GREEN, "risk.none_high",
                          "1 open item, not high-impact." if n == 1 else f"{n} open items, none high-impact.",
                          gaps, summary="no open risk is high-impact")
    return RuleResult(dim, Status.GREEN, "risk.none_open", "No open risks or issues.", gaps,
                      summary="no risks or issues are open")


# --- Overall ------------------------------------------------------------------------------

RULES = (score_schedule, score_budget, score_scope, score_risk)


@dataclass(frozen=True)
class Scorecard:
    dimensions: list[RuleResult]
    overall: Status
    overall_reason: str
    low_confidence: bool
    gaps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "overall_reason": self.overall_reason,
            "low_confidence": self.low_confidence,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "gaps": list(self.gaps),
        }


def report_gaps(facts: Facts, already_said: str = "") -> list[str]:
    """Gaps in the parts of a status report that no rule scores. Items a rule's reason already names
    (already_said) aren't repeated."""
    checks = [
        (facts.project_name, "There's no project name."),
        (facts.as_of_date, "There's no report date."),
        (facts.accomplishments, "No accomplishments are listed for this period."),
        (facts.next_steps, "No next steps are listed."),
    ]
    gaps = [msg for value, msg in checks if not value]
    # Low-impact items without an owner aren't worth a reader's attention here.
    gaps += [f"{_q(_label(r))} has no owner." for r in facts.risks or []
             if r.state != "closed" and r.impact != "low" and not r.owner and _q(_label(r)) not in already_said]
    return gaps


def score(facts: Facts, t: Thresholds | None = None) -> Scorecard:
    t = t or load_thresholds()
    results = [rule(facts, t) for rule in RULES]
    known = [r for r in results if r.status is not Status.UNKNOWN]
    unknown = [r.dimension for r in results if r.status is Status.UNKNOWN]

    if known:
        worst = max(known, key=lambda r: _SEVERITY[r.status])
        overall = worst.status
        drivers = [r.dimension for r in known if r.status is overall]
        reason = f"Worst known dimension: {', '.join(drivers)} ({overall.value})."
    else:
        overall = Status.UNKNOWN
        reason = "No dimension could be scored from the notes."
    low_confidence = len(unknown) >= t.low_confidence_unknown_count
    if low_confidence and known:
        reason += f" Low confidence: {', '.join(unknown)} could not be scored."

    gaps = [g for r in results for g in r.gaps] + report_gaps(facts, " ".join(r.reason for r in results))
    return Scorecard(results, overall, reason, low_confidence, list(dict.fromkeys(gaps)))
