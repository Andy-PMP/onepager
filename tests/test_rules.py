from dataclasses import replace
from datetime import date

import pytest

from onepager.rules import (
    Status,
    Thresholds,
    has_estimate,
    load_thresholds,
    report_gaps,
    score,
    score_budget,
    score_risk,
    score_schedule,
    score_scope,
)
from onepager.schema import Budget, Facts, Milestone, Risk, ScopeChange, UnforecastCost

T = Thresholds()
AS_OF = date(2026, 6, 1)


def ms(name="M1", planned=date(2026, 7, 1), forecast=None, actual=None, critical=None, recovery=None):
    return Milestone(name, planned, forecast, actual, critical, recovery)


def days_after(d: date, n: int) -> date:
    return date.fromordinal(d.toordinal() + n)


def schedule(*milestones, as_of=AS_OF):
    return score_schedule(Facts(as_of_date=as_of, milestones=list(milestones)), T)


# --- Thresholds file ----------------------------------------------------------------------


def test_thresholds_file_matches_defaults():
    # The defaults mirror the brief; if the file is tuned, update this test on purpose.
    assert load_thresholds() == Thresholds()


# --- Schedule -----------------------------------------------------------------------------


class TestSchedule:
    def test_no_milestones_is_unknown(self):
        for milestones in (None, []):
            r = score_schedule(Facts(milestones=milestones), T)
            assert (r.status, r.rule) == (Status.UNKNOWN, "schedule.no_milestones")
            assert r.gaps

    def test_undated_milestones_are_unknown(self):
        r = schedule(ms(planned=None))
        assert (r.status, r.rule) == (Status.UNKNOWN, "schedule.no_dates")

    def test_on_track_is_green(self):
        p = date(2026, 7, 1)
        r = schedule(ms(planned=p), ms("M2", planned=p, forecast=p, critical=True))
        assert (r.status, r.rule) == (Status.GREEN, "schedule.on_track")

    def test_early_completion_is_green(self):
        p = date(2026, 5, 1)
        r = schedule(ms(planned=p, actual=days_after(p, -3), critical=True))
        assert r.status is Status.GREEN

    @pytest.mark.parametrize("slip, expected", [(1, Status.AMBER), (14, Status.AMBER), (15, Status.RED)])
    def test_critical_slip_boundary(self, slip, expected):
        p = date(2026, 7, 1)
        r = schedule(ms(planned=p, forecast=days_after(p, slip), critical=True))
        assert r.status is expected
        assert str(slip) in r.reason

    def test_one_day_slip_reason_is_singular(self):
        p = date(2026, 7, 1)
        assert schedule(ms(planned=p, forecast=days_after(p, 1))).reason.endswith("1 day.")

    def test_large_non_critical_slip_is_amber(self):
        p = date(2026, 7, 1)
        r = schedule(ms(planned=p, forecast=days_after(p, 60), critical=False))
        assert (r.status, r.rule) == (Status.AMBER, "schedule.slip")
        assert "non-critical" in r.reason

    def test_large_slip_with_unknown_criticality_is_amber_and_flags_gap(self):
        p = date(2026, 7, 1)
        r = schedule(ms("Cutover", planned=p, forecast=days_after(p, 30)))
        assert r.status is Status.AMBER
        assert any("Cutover" in g for g in r.gaps)

    def test_actual_date_counts_as_slip(self):
        p = date(2026, 5, 1)
        r = schedule(ms(planned=p, actual=days_after(p, 20), critical=True))
        assert r.status is Status.RED

    def test_reports_largest_critical_slip(self):
        p = date(2026, 7, 1)
        r = schedule(ms("A", planned=p, forecast=days_after(p, 20), critical=True),
                     ms("B", planned=p, forecast=days_after(p, 40), critical=True))
        assert "'B'" in r.reason and "40" in r.reason

    def test_missed_without_recovery_is_red(self):
        r = schedule(ms("Go-live", planned=date(2026, 5, 15)))
        assert (r.status, r.rule) == (Status.RED, "schedule.missed_no_recovery")
        assert "Go-live" in r.reason

    def test_missed_with_recovery_plan_is_amber(self):
        r = schedule(ms(planned=date(2026, 5, 15), recovery="Extra weekend shift"))
        assert (r.status, r.rule) == (Status.AMBER, "schedule.missed_with_recovery")

    def test_past_milestone_with_new_date_is_a_slip_not_a_miss(self):
        p = date(2026, 5, 25)
        r = schedule(ms(planned=p, forecast=days_after(p, 10), critical=True))
        assert (r.status, r.rule) == (Status.AMBER, "schedule.slip")

    def test_no_report_date_skips_missed_check_and_flags_gap(self):
        r = schedule(ms(planned=date(2020, 1, 1)), as_of=None)
        assert r.status is Status.GREEN
        assert any("report date" in g for g in r.gaps)

    def test_critical_slip_outranks_missed_date(self):
        p = date(2026, 7, 1)
        r = schedule(ms("Late", planned=date(2026, 5, 1)),
                     ms("Critical", planned=p, forecast=days_after(p, 30), critical=True))
        assert r.rule == "schedule.critical_slip"

    def test_threshold_is_configurable(self):
        p = date(2026, 7, 1)
        f = Facts(as_of_date=AS_OF, milestones=[ms(planned=p, forecast=days_after(p, 10), critical=True)])
        assert score_schedule(f, replace(T, critical_slip_red_days=7)).status is Status.RED


# --- Budget -------------------------------------------------------------------------------


def budget(**kw):
    return score_budget(Facts(budget=Budget(**kw)), T)


class TestBudget:
    def test_no_budget_is_unknown(self):
        r = score_budget(Facts(budget=None), T)
        assert (r.status, r.rule) == (Status.UNKNOWN, "budget.no_plan")
        assert r.gaps == ["No budget figures provided"]

    def test_plan_only_is_unknown(self):
        assert budget(planned=100).rule == "budget.no_actuals"

    def test_spend_without_plan_is_unknown(self):
        assert budget(actual=100).rule == "budget.no_plan"

    def test_zero_plan_is_unknown(self):
        assert budget(planned=0, forecast=10).rule == "budget.invalid_plan"

    @pytest.mark.parametrize(
        "forecast, expected",
        [(80, Status.GREEN), (100, Status.GREEN), (105, Status.GREEN), (105.01, Status.AMBER),
         (110, Status.AMBER), (110.01, Status.RED), (150, Status.RED)],
    )
    def test_overrun_boundaries(self, forecast, expected):
        assert budget(planned=100, forecast=forecast).status is expected

    def test_forecast_preferred_over_actual(self):
        r = budget(planned=100, actual=50, forecast=120)
        assert r.status is Status.RED
        assert r.reason.startswith("Forecast")
        assert r.gaps == []

    def test_actual_used_when_no_forecast_and_flags_gap(self):
        r = budget(planned=100, actual=108)
        assert r.status is Status.AMBER
        assert r.reason.startswith("Actual")
        assert r.gaps

    def test_reason_shows_figures_and_currency(self):
        r = budget(planned=2_000_000, forecast=2_300_000, currency="USD")
        assert r.reason == "Forecast 2,300,000 USD vs plan 2,000,000 USD (+15.0%)."

    def test_currency_symbol_goes_first(self):
        r = budget(planned=380_000, forecast=428_000, currency="$")
        assert r.reason == "Forecast $428,000 vs plan $380,000 (+12.6%)."


# --- Scope --------------------------------------------------------------------------------


def scope(*changes, milestones=None):
    return score_scope(Facts(scope_changes=None if changes == (None,) else list(changes), milestones=milestones), T)


class TestScope:
    def test_not_mentioned_is_unknown(self):
        r = scope(None)
        assert (r.status, r.rule) == (Status.UNKNOWN, "scope.not_mentioned")

    def test_explicitly_no_changes_is_green(self):
        assert scope().rule == "scope.no_changes"

    def test_resolved_changes_are_green(self):
        r = scope(ScopeChange("Add SSO", "approved"), ScopeChange("Add mobile", "rejected"))
        assert (r.status, r.rule) == (Status.GREEN, "scope.all_resolved")

    def test_pending_change_is_amber(self):
        r = scope(ScopeChange("Add SSO", "pending"), ScopeChange("Add audit log", "approved"))
        assert (r.status, r.rule) == (Status.AMBER, "scope.pending_changes")
        assert "1 change request pending" in r.reason

    def test_unknown_approval_counts_as_pending_and_flags_gap(self):
        r = scope(ScopeChange("Add SSO"))
        assert r.status is Status.AMBER
        assert r.gaps

    def test_unapproved_change_on_critical_milestone_is_red(self):
        r = scope(ScopeChange("Add SSO", "pending", "go-live"), milestones=[ms("Go-Live", critical=True)])
        assert (r.status, r.rule) == (Status.RED, "scope.unapproved_critical")

    def test_unapproved_change_on_non_critical_milestone_is_amber(self):
        r = scope(ScopeChange("Add SSO", "pending", "Training"), milestones=[ms("Training", critical=False)])
        assert r.status is Status.AMBER

    def test_approved_change_on_critical_milestone_is_green(self):
        r = scope(ScopeChange("Add SSO", "approved", "Go-live"), milestones=[ms("Go-live", critical=True)])
        assert r.status is Status.GREEN

    def test_unmatched_milestone_name_is_not_critical(self):
        r = scope(ScopeChange("Add SSO", "pending", "Phase 9"), milestones=[ms("Go-live", critical=True)])
        assert r.status is Status.AMBER


# --- Risk ---------------------------------------------------------------------------------


def risk(*risks):
    return score_risk(Facts(risks=None if risks == (None,) else list(risks)), T)


class TestRisk:
    def test_not_mentioned_is_unknown(self):
        assert risk(None).status is Status.UNKNOWN

    def test_explicitly_none_is_green(self):
        assert risk().rule == "risk.none_open"

    def test_only_low_and_medium_is_green(self):
        r = risk(Risk("Vendor delay", impact="medium"), Risk("Typo in docs", impact="low"))
        assert (r.status, r.rule) == (Status.GREEN, "risk.none_high")

    def test_high_with_owner_and_mitigation_is_amber(self):
        r = risk(Risk("Data loss", impact="high", owner="Priya", mitigation="Dual backups"))
        assert (r.status, r.rule) == (Status.AMBER, "risk.high_managed")

    @pytest.mark.parametrize("owner, mitigation, missing", [
        (None, "Dual backups", "no owner"),
        ("Priya", None, "no mitigation"),
        (None, None, "no owner and mitigation"),
    ])
    def test_high_missing_owner_or_mitigation_is_red(self, owner, mitigation, missing):
        r = risk(Risk("Data loss", impact="high", owner=owner, mitigation=mitigation))
        assert (r.status, r.rule) == (Status.RED, "risk.high_unmanaged")
        assert missing in r.reason

    def test_closed_high_risk_is_ignored(self):
        assert risk(Risk("Data loss", impact="high", state="closed")).rule == "risk.none_open"

    def test_issue_kind_appears_in_reason(self):
        r = risk(Risk("Switch failed", kind="issue", impact="high"))
        assert "High-impact issue" in r.reason

    def test_unrated_impact_is_not_high_but_flags_gap(self):
        r = risk(Risk("Something odd"))
        assert r.status is Status.GREEN
        assert r.gaps


# --- Overall ------------------------------------------------------------------------------


def full_facts(**overrides):
    base = Facts(
        project_name="Atlas",
        as_of_date=AS_OF,
        milestones=[ms(planned=date(2026, 7, 1))],
        budget=Budget(planned=100, forecast=100),
        scope_changes=[],
        risks=[],
        accomplishments=["Racked servers"],
        next_steps=["Cut over"],
    )
    return replace(base, **overrides)


class TestOverall:
    def test_all_green(self):
        card = score(full_facts())
        assert card.overall is Status.GREEN
        assert not card.low_confidence
        assert card.gaps == []

    def test_worst_known_dimension_wins(self):
        card = score(full_facts(budget=Budget(planned=100, forecast=108),
                                risks=[Risk("Outage", impact="high")]))
        assert card.overall is Status.RED
        assert "risk" in card.overall_reason and "budget" not in card.overall_reason

    def test_one_unknown_is_not_low_confidence(self):
        card = score(full_facts(budget=None))
        assert card.overall is Status.GREEN
        assert not card.low_confidence
        assert "No budget figures provided" in card.gaps

    def test_two_unknowns_is_low_confidence(self):
        card = score(full_facts(budget=None, scope_changes=None))
        assert card.overall is Status.GREEN
        assert card.low_confidence
        assert "budget" in card.overall_reason and "scope" in card.overall_reason

    def test_all_unknown(self):
        card = score(Facts())
        assert card.overall is Status.UNKNOWN
        assert card.low_confidence
        assert [d.status for d in card.dimensions] == [Status.UNKNOWN] * 4

    def test_dimension_order_and_dict_shape(self):
        d = score(full_facts()).to_dict()
        assert [x["dimension"] for x in d["dimensions"]] == ["schedule", "budget", "scope", "risk"]
        assert d["overall"] == "green"
        assert all({"status", "rule", "reason", "gaps"} <= x.keys() for x in d["dimensions"])

    def test_gaps_are_deduplicated(self):
        card = score(Facts())
        assert len(card.gaps) == len(set(card.gaps))


class TestReportGaps:
    def test_complete_report_has_no_gaps(self):
        assert report_gaps(full_facts()) == []

    def test_missing_basics(self):
        gaps = report_gaps(Facts())
        assert "No project name" in gaps
        assert "No report date" in gaps
        assert "No accomplishments listed for the period" in gaps
        assert "No next steps listed" in gaps

    def test_open_risk_without_owner_is_named(self):
        gaps = report_gaps(full_facts(risks=[Risk("Vendor attrition", impact="medium"), Risk("Done", owner="A"),
                                             Risk("Minor leave cover", impact="low")]))
        assert "No owner for: Vendor attrition" in gaps
        assert not any("Minor leave cover" in g for g in gaps)

    def test_owner_gap_skips_items_a_rule_already_named(self):
        facts = full_facts(risks=[Risk("Scanner firmware", impact="high"), Risk("Leave cover", impact="medium")])
        card = score(facts)
        assert "Scanner firmware" in card.dimensions[3].reason
        assert "No owner for: Leave cover" in card.gaps
        assert not any("Scanner firmware" in g and g.startswith("No owner") for g in card.gaps)


class TestNewGaps:
    def test_undated_milestones_are_named(self):
        r = schedule(ms("Raleigh go-live", planned=date(2026, 7, 1)), ms("Greensboro phase 2", planned=None),
                     # Regressions from the regenerated samples: these have dates, just not planned ones.
                     ms("Wave 2", planned=None, forecast=date(2026, 11, 6)),
                     ms("Contract signed", planned=None, actual=date(2026, 9, 4)))
        assert "No date for: Greensboro phase 2" in r.gaps

    def test_unforecast_costs_show_adjusted_figure_without_changing_status(self):
        b = Budget(planned=1_200_000, forecast=1_284_000, currency="$",
                   unforecast_costs=[UnforecastCost("weekend overtime for cutover", 18_000)])
        r = score_budget(Facts(budget=b), T)
        assert r.status is Status.AMBER
        assert r.reason == "Forecast $1,284,000 vs plan $1,200,000 (+7.0%)."
        assert r.gaps == ["The forecast excludes $18,000 of known costs (weekend overtime for cutover). "
                          "Including them: $1,302,000 vs plan $1,200,000 (+8.5%)."]

    def test_unpriced_unforecast_costs_are_listed(self):
        b = Budget(planned=100, forecast=100, unforecast_costs=[UnforecastCost("legal review")])
        assert score_budget(Facts(budget=b), T).gaps == [
            "Known costs not in the forecast, with no amount given: legal review"]

    @pytest.mark.parametrize("text, expected", [
        ("$20K", True), ("€1.2M extra", True), ("adds 2 weeks", True), ("+10 days", True), ("3 wks", True),
        ("new date 2027-02-15", True), ("about 40k", True),
        # Regression from the user's WMS test: naming a phase isn't an estimate, even with a digit in it.
        ("Would affect UAT phase 2 timing only", False), ("minor", False), (None, False), ("CR-14", False),
    ])
    def test_what_counts_as_an_estimate(self, text, expected):
        assert has_estimate(text) is expected

    def test_pending_change_without_estimate(self):
        r = scope(ScopeChange("CR-14 returns module", "pending"),
                  ScopeChange("CR-15 dashboards", "pending", impact_estimate="$20K, 2 weeks"),
                  ScopeChange("CR-12 report", "approved"))
        assert "No cost or schedule estimate for: CR-14 returns module" in r.gaps
        assert not any("CR-15" in g or "CR-12" in g for g in r.gaps)

    def test_high_risk_without_timing(self):
        r = risk(Risk("Firmware not certified", impact="high"),
                 Risk("Peak season", impact="high", owner="Dana", mitigation="No-go call", resolve_by="2027-01-15"),
                 Risk("Minor", impact="low"))
        assert "No target date for resolving: Firmware not certified" in r.gaps
        assert not any("Peak season" in g or "Minor" in g for g in r.gaps)

    def test_titles_are_used_in_reasons_and_gaps(self):
        # Regression from the WMS review: "…firmware update that…" read as broken.
        r = risk(Risk("Handheld scanner firmware: units need an update the vendor hasn't certified", kind="issue",
                      impact="high", title="Scanner firmware certification"))
        assert r.reason == "High-impact issue 'Scanner firmware certification' has no owner and mitigation."
        assert "No target date for resolving: Scanner firmware certification" in r.gaps
        s = scope(ScopeChange("CR-14: Add returns processing to phase 1", "pending", title="CR-14 returns module"))
        assert "No cost or schedule estimate for: CR-14 returns module" in s.gaps

    def test_long_descriptions_are_shortened_in_reasons(self):
        long = "Handheld scanner firmware: units need an update the vendor hasn't certified, so pickers can't " \
               "use the new system at go-live"
        reason = risk(Risk(long, kind="issue", impact="high")).reason
        assert len(reason) < 140
        assert "…" in reason and reason.startswith("High-impact issue 'Handheld scanner firmware")
