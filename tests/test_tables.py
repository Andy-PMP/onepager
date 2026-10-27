"""Deterministic table parsing (BUG-3/4/5 from the Harbor Street report)."""

from datetime import date
from pathlib import Path

import pytest

from onepager.schema import Facts
from onepager.tables import apply_tables, parse_date, parse_number, parse_tables

ROOT = Path(__file__).resolve().parents[1]
HARBOR = (ROOT / "evals" / "cases" / "harbor-street.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("cell, value", [
    ("210000", 210000), ("-4000", -4000), ("(4,000)", -4000), ("$1,234", 1234), ("62k", 62000), ("1.2M", 1.2e6),
    ("", None), ("n/a", None), ("+3 weeks", None),
])
def test_parse_number(cell, value):
    assert parse_number(cell) == value


def test_parse_date():
    assert parse_date("2026-10-27") == date(2026, 10, 27)
    assert parse_date("10/27/2026") == date(2026, 10, 27)
    assert parse_date("Q3") is None


class TestBudgetTables:
    def test_sums_category_lines_without_a_total_row(self):
        b = parse_tables(HARBOR).budget
        assert (b.planned, b.forecast) == (480000, 455500)

    def test_uses_the_total_row_when_present(self):
        notes = "Category,Planned,Forecast\nA,100,90\nB,50,60\nTotal,150,150\n"
        b = parse_tables(notes).budget
        assert (b.planned, b.forecast) == (150, 150)

    def test_negative_values_and_quoted_numbers_with_commas(self):
        notes = 'Line,Budget,Forecast\nWorks,"1,000","1,200"\nCredit,0,-200\nFees,"2,500","2,400"\n'
        b = parse_tables(notes).budget
        assert (b.planned, b.forecast) == (3500, 3400)

    def test_prose_with_commas_is_not_a_table(self):
        notes = "attendees: Renata (PM), Dmitri (infra), Jo (apps)\nwave 1 done, 14 apps moved, no sev1s\n"
        parsed = parse_tables(notes)
        assert parsed.budget is None and not parsed.tasks and parsed.scope_changes is None


class TestTaskTables:
    def test_harbor_tasks(self):
        tasks = {t.name: t for t in parse_tables(HARBOR).tasks}
        assert len(tasks) == 10
        assert tasks["Demolition complete"].complete and tasks["Demolition complete"].actual == date(2026, 10, 23)
        assert tasks["Move weekend"].critical is True and not tasks["Move weekend"].complete
        assert tasks["Furniture delivery"].forecast == date(2026, 12, 29)

    def test_office_move_export_with_summary_rows(self):
        notes = (ROOT / "samples" / "office-move.txt").read_text(encoding="utf-8")
        tasks = parse_tables(notes).tasks
        assert len(tasks) == 8  # the BUDGET SUMMARY and RISK SUMMARY rows have no dates
        assert tasks[0].actual == date(2026, 6, 10)  # from the Actual Finish column


class TestChangeRequestTables:
    def test_harbor_change_requests(self):
        cr02, cr03 = parse_tables(HARBOR).scope_changes
        assert (cr02.status, cr02.cost) == ("approved", -4000)
        assert cr03.status == "pending" and cr03.cost == 62000 and cr03.impact_estimate == "+3 weeks"
        assert cr03.affected_milestone == "Construction substantially complete; Move weekend"
        assert cr03.title == "CR-03: Build out 2nd floor east wing as lab space"


class TestApplyTables:
    def apply(self, **facts):
        base = Facts(as_of_date=date(2026, 10, 27), **facts)
        return apply_tables(base, parse_tables(HARBOR), HARBOR, 14, 30)

    def test_accomplishments_are_tasks_finished_in_the_window(self):
        # BUG-4: lease (August) and design (September) are outside the 14-day window.
        facts = self.apply(accomplishments=["Lease signed", "Space design approved", "Demolition complete"])
        assert facts.accomplishments == ["Demolition complete"]

    def test_next_steps_are_tasks_due_in_the_look_ahead_plus_free_text(self):
        # BUG-5: only what's due within 30 days, task names as written, plus non-task items kept.
        facts = self.apply(next_steps=["Complete construction substantially",
                                       "Sponsor decision on CR-03 by 2026-11-13"])
        assert facts.next_steps == ["Network cabling rough-in (due 2026-10-30)",
                                    "Employee move communications (due 2026-11-20)",
                                    "Sponsor decision on CR-03 by 2026-11-13"]

    @pytest.mark.parametrize("as_of, expected", [
        (date(2026, 11, 6), ["Demolition complete"]),   # 14 days after 23 Oct: still in
        (date(2026, 11, 7), []),                        # 15 days: out
        (date(2026, 10, 22), []),                       # before it finished
    ])
    def test_accomplishment_window_boundaries(self, as_of, expected):
        facts = apply_tables(Facts(as_of_date=as_of), parse_tables(HARBOR), HARBOR, 14, 30)
        assert facts.accomplishments == expected

    def test_budget_and_scope_replace_extraction(self):
        facts = self.apply()
        assert (facts.budget.planned, facts.budget.forecast) == (480000, 455500)
        assert [c.title.split(":")[0] for c in facts.scope_changes] == ["CR-02", "CR-03"]
        assert len(facts.milestones) == 10

    def test_no_tables_changes_nothing(self):
        facts = Facts(accomplishments=["x"])
        assert apply_tables(facts, parse_tables("just prose, no table"), "", 14, 30) is facts
