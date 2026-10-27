"""Deterministic status rules. No LLM here: each rule is a pure function of the extracted facts.

Every rule returns the status, an id for the branch that fired, a plain-language reason (shown
in the "How status was decided" panel) and any gaps it found in the data.
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
    )


@dataclass(frozen=True)
class RuleResult:
    dimension: str
    status: Status
    rule: str
    reason: str
    gaps: list[str] = field(default_factory=list)
    # A plain clause for the executive summary ("Cutover has slipped 21 days to 2026-12-11"). Written by code
    # from the same facts as the reason, so it can't invent links between them. Empty for green and unknown.
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status.value,
            "rule": self.rule,
            "reason": self.reason,
            "gaps": list(self.gaps),
        }


def _short(text: str, limit: int = 80) -> str:
    """Trim a quoted description so a reason or gap stays one line."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _names(items: list[str]) -> str:
    return "; ".join(_short(x) for x in items)


def _label(item: Risk | ScopeChange) -> str:
    """The short title when extraction gave one, else the description cut to fit."""
    return item.title or _short(item.description)


# An estimate means an amount, a duration or a date. Naming the phase a change affects isn't one,
# and the model kept counting that, so code makes the call.
_ESTIMATE = re.compile(
    r"[$€£]\s?\d|\b\d[\d,.]*\s?(k|m|bn|million|thousand|days?|weeks?|wks?|months?)\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


def has_estimate(text: str | None) -> bool:
    return bool(text and _ESTIMATE.search(text))


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
    n = f"{days} day{'s' if days != 1 else ''}"
    if m.actual_date:
        return f"{m.name} finished {n} late, on {m.actual_date.isoformat()}"
    return f"{m.name} slipped {n} to {m.forecast_date.isoformat()}"  # "slipped" reads right for plural names too


def score_schedule(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "schedule"
    milestones = facts.milestones
    if not milestones:
        return RuleResult(dim, Status.UNKNOWN, "schedule.no_milestones",
                          "The notes don't list any milestones.", ["No milestones or dates provided"])
    dated = [m for m in milestones if m.planned_date is not None]
    if not dated:
        return RuleResult(dim, Status.UNKNOWN, "schedule.no_dates",
                          "Milestones are named but none has a planned date.",
                          [f"No date for: {_names([m.name for m in milestones])}"])

    gaps: list[str] = []
    if facts.as_of_date is None:
        gaps.append("No report date, so missed milestones can't be detected")
    undated = [m.name for m in milestones if not (m.planned_date or m.forecast_date or m.actual_date)]
    if undated:
        gaps.append(f"No date for: {_names(undated)}")
    unrated = [m.name for m in dated if (_slip_days(m) or 0) > t.critical_slip_red_days and m.is_critical is None]
    if unrated:
        gaps.append(f"Not stated whether these slipped milestones are critical: {', '.join(unrated)}")

    critical_slips = [(m, d) for m in dated if m.is_critical and (d := _slip_days(m)) is not None
                      and d > t.critical_slip_red_days]
    if critical_slips:
        m, d = max(critical_slips, key=lambda x: x[1])
        return RuleResult(dim, Status.RED, "schedule.critical_slip",
                          f"Critical milestone '{m.name}' has slipped {d} days "
                          f"(more than {t.critical_slip_red_days}).", gaps,
                          summary=_slip_clause(m, d))

    missed = [m for m in dated if _is_missed(m, facts.as_of_date)]
    unplanned = [m for m in missed if not m.recovery_plan]
    if unplanned:
        m = unplanned[0]
        return RuleResult(dim, Status.RED, "schedule.missed_no_recovery",
                          f"'{m.name}' was due {m.planned_date.isoformat()}, "
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
                          f"Largest slip: {label} '{m.name}', {d} day{'s' if d != 1 else ''}{extra}.", gaps,
                          summary=_slip_clause(m, d) + (f" ({others} other milestone{'s' if others != 1 else ''} "
                                                         "also slipped)" if others else ""))
    if missed:
        m = missed[0]
        return RuleResult(dim, Status.AMBER, "schedule.missed_with_recovery",
                          f"'{m.name}' missed its date but has a recovery plan.", gaps,
                          summary=f"{m.name} missed its {m.planned_date.isoformat()} date; a recovery plan is "
                                  "in place")

    return RuleResult(dim, Status.GREEN, "schedule.on_track",
                      f"No slips across {len(dated)} dated milestone{'s' if len(dated) != 1 else ''}.", gaps)


# --- Budget -------------------------------------------------------------------------------


def _money(value: float, b: Budget) -> str:
    amount = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    if not b.currency:
        return amount
    # Symbols go in front ($2,400,000); codes go after (2,400,000 USD).
    return f"{b.currency}{amount}" if len(b.currency) == 1 else f"{amount} {b.currency}"


def _unforecast_gaps(b: Budget, compare: float, label: str) -> list[str]:
    """Known costs the forecast leaves out. Reported with the adjusted figure; the status stays on the forecast."""
    priced = [c for c in b.unforecast_costs if c.amount is not None]
    unpriced = [c.description for c in b.unforecast_costs if c.amount is None]
    gaps = []
    if priced:
        extra = sum(c.amount for c in priced)
        adjusted = compare + extra
        pct = (adjusted - b.planned) / b.planned * 100
        what = _names([c.description for c in priced])
        gaps.append(f"The {label} excludes {_money(extra, b)} of known costs ({what}). "
                    f"Including them: {_money(adjusted, b)} vs plan {_money(b.planned, b)} ({pct:+.1f}%).")
    if unpriced:
        gaps.append(f"Known costs not in the {label}, with no amount given: {_names(unpriced)}")
    return gaps


def score_budget(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "budget"
    b = facts.budget
    if b is None or b.planned is None:
        return RuleResult(dim, Status.UNKNOWN, "budget.no_plan",
                          "No planned budget figure in the notes.", ["No budget figures provided"])
    if b.planned <= 0:
        return RuleResult(dim, Status.UNKNOWN, "budget.invalid_plan",
                          "The planned budget isn't a positive number.", ["Planned budget figure is unclear"])
    compare, label = (b.forecast, "forecast") if b.forecast is not None else (b.actual, "actual")
    if compare is None:
        return RuleResult(dim, Status.UNKNOWN, "budget.no_actuals",
                          "A planned budget is given but no actual or forecast spend.",
                          ["No actual or forecast spend against the budget"])

    overrun = (compare - b.planned) / b.planned * 100
    detail = f"{label.capitalize()} {_money(compare, b)} vs plan {_money(b.planned, b)} ({overrun:+.1f}%)."
    gaps = [] if b.forecast is not None else ["No forecast at completion; compared actual spend to date"]
    gaps += _unforecast_gaps(b, compare, label)
    clause = (f"the budget {'forecast' if label == 'forecast' else 'spend to date'} is {_money(compare, b)} "
              f"against a {_money(b.planned, b)} plan ({overrun:+.1f}%)")
    if overrun <= t.green_max_overrun_pct:
        return RuleResult(dim, Status.GREEN, "budget.within_tolerance", detail, gaps)
    if overrun <= t.amber_max_overrun_pct:
        return RuleResult(dim, Status.AMBER, "budget.minor_overrun", detail, gaps, summary=clause)
    return RuleResult(dim, Status.RED, "budget.major_overrun", detail, gaps, summary=clause)


# --- Scope --------------------------------------------------------------------------------


def score_scope(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "scope"
    changes = facts.scope_changes
    if changes is None:
        return RuleResult(dim, Status.UNKNOWN, "scope.not_mentioned",
                          "The notes don't say whether scope changed.", ["No information on scope changes"])

    critical = {m.name.casefold() for m in facts.milestones or [] if m.is_critical}
    # Rejected changes are closed; anything else not yet approved is still pending.
    pending = [c for c in changes if c.status not in ("approved", "rejected")]
    hits_critical = [c for c in pending if c.affected_milestone and c.affected_milestone.casefold() in critical]
    gaps = []
    if any(c.status is None for c in changes):
        gaps.append("Approval status not stated for some scope changes")
    unestimated = [_label(c) for c in pending if not has_estimate(c.impact_estimate)]
    if unestimated:
        gaps.append(f"No cost or schedule estimate for: {_names(unestimated)}")

    if hits_critical:
        c = hits_critical[0]
        return RuleResult(dim, Status.RED, "scope.unapproved_critical",
                          f"Unapproved change '{_label(c)}' affects critical milestone "
                          f"'{c.affected_milestone}'.", gaps,
                          summary=f"unapproved scope change {_label(c)} would land on critical milestone "
                                  f"{c.affected_milestone}")
    if pending:
        n = len(pending)
        titles = _names([_label(c) for c in pending])
        return RuleResult(dim, Status.AMBER, "scope.pending_changes",
                          f"{n} change request{'s' if n != 1 else ''} pending approval.", gaps,
                          summary=f"{n} change request{'s await' if n != 1 else ' awaits'} approval ({titles})")
    if changes:
        return RuleResult(dim, Status.GREEN, "scope.all_resolved",
                          f"All {len(changes)} scope change{'s' if len(changes) != 1 else ''} approved or rejected.",
                          gaps)
    return RuleResult(dim, Status.GREEN, "scope.no_changes", "No scope changes reported.", gaps)


# --- Risk ---------------------------------------------------------------------------------


def score_risk(facts: Facts, t: Thresholds) -> RuleResult:
    dim = "risk"
    risks = facts.risks
    if risks is None:
        return RuleResult(dim, Status.UNKNOWN, "risk.not_mentioned",
                          "The notes don't mention risks or issues.", ["No risks or issues listed"])

    open_risks = [r for r in risks if r.state != "closed"]
    high = [r for r in open_risks if r.impact in t.high_impact_levels]
    gaps = []
    unrated = sum(1 for r in open_risks if r.impact is None)
    if unrated:
        gaps.append(f"{unrated} risk{'s' if unrated != 1 else ''} or issue{'s' if unrated != 1 else ''} "
                    "without a stated impact")
    untimed = [_label(r) for r in high if not r.resolve_by]
    if untimed:
        gaps.append(f"No target date for resolving: {_names(untimed)}")

    uncovered = [r for r in high if not r.owner or not r.mitigation]
    if uncovered:
        r = uncovered[0]
        missing = " and ".join(x for x, v in (("owner", r.owner), ("mitigation", r.mitigation)) if not v)
        extra = f" ({len(uncovered)} such items)" if len(uncovered) > 1 else ""
        others = len(uncovered) - 1
        return RuleResult(dim, Status.RED, "risk.high_unmanaged",
                          f"High-impact {r.kind or 'risk'} '{_label(r)}' has no {missing}{extra}.",
                          gaps,
                          summary=f"high-impact {r.kind or 'risk'} {_label(r)} has no {missing}"
                                  + (f" ({others} more high-impact item{'s' if others != 1 else ''} lack "
                                     "an owner or mitigation)" if others else ""))
    if high:
        n = len(high)
        return RuleResult(dim, Status.AMBER, "risk.high_managed",
                          f"{n} open high-impact item{'s' if n != 1 else ''}, each with an owner and mitigation.",
                          gaps,
                          summary=f"{n} high-impact risk{'s or issues are' if n != 1 else ' or issue is'} open "
                                  f"({_names([_label(r) for r in high])}), "
                                  f"{'each ' if n != 1 else ''}with an owner and mitigation")
    if open_risks:
        return RuleResult(dim, Status.GREEN, "risk.none_high",
                          f"{len(open_risks)} open item{'s' if len(open_risks) != 1 else ''}, none high-impact.",
                          gaps)
    return RuleResult(dim, Status.GREEN, "risk.none_open", "No open risks or issues.", gaps)


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
        (facts.project_name, "No project name"),
        (facts.as_of_date, "No report date"),
        (facts.accomplishments, "No accomplishments listed for the period"),
        (facts.next_steps, "No next steps listed"),
    ]
    gaps = [msg for value, msg in checks if not value]
    # Low-impact items without an owner aren't worth a reader's attention here.
    ownerless = [_label(r) for r in facts.risks or []
                 if r.state != "closed" and r.impact != "low" and not r.owner
                 and _label(r) not in already_said]
    if ownerless:
        gaps.append(f"No owner for: {_names(ownerless)}")
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
