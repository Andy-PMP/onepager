import pytest

from onepager.rules import RuleResult, Scorecard, Status
from onepager.schema import SchemaError
from onepager.validate import (
    find_contradictions,
    find_dates,
    find_numbers,
    parse_summary,
    unsupported_figures,
)


def card(overall=Status.RED, **dims):
    statuses = {"schedule": Status.RED, "budget": Status.AMBER, "scope": Status.GREEN, "risk": Status.AMBER} | dims
    results = [RuleResult(d, s, f"{d}.x", "reason") for d, s in statuses.items()]
    return Scorecard(results, overall, "Worst known dimension.", False, [])


# --- Summary shape ------------------------------------------------------------------------


def test_parses_summary():
    assert parse_summary({"executive_summary": "  Red.  "}) == "Red."


@pytest.mark.parametrize("data, message", [
    ({"executive_summary": ""}, "non-empty"),
    ({"executive_summary": "x" * 1300}, "longer"),
    ({"executive_summary": 3}, "non-empty"),
    ({"executive_summary": "ok", "accomplishments": []}, "only executive_summary"),
    # The garbled tool output seen from Haiku 4.5 in testing
    ({"executive_summary": "\n<item>Wave 1 done</item>\n</invoke>"}, "markup"),
    ("Red.", "only executive_summary"),
])
def test_rejects_bad_summary(data, message):
    with pytest.raises(SchemaError, match=message):
        parse_summary(data)


# --- Contradictions -----------------------------------------------------------------------


class TestContradictions:
    def test_matching_colors_pass(self):
        texts = ["The project is red because the schedule is red. Budget is amber.", "Scope stays green."]
        assert find_contradictions(texts, card()) == []

    def test_wrong_dimension_color_is_flagged(self):
        problems = find_contradictions(["Budget is green this week."], card())
        assert len(problems) == 1 and "green" in problems[0]

    def test_overall_claim_without_dimension_is_checked_against_overall(self):
        assert find_contradictions(["Overall the project is green."], card())

    def test_color_matching_any_mentioned_dimension_passes(self):
        # Red matches the schedule even though risk (also mentioned) is amber.
        assert find_contradictions(["Schedule is red because of the storage risk."], card()) == []

    def test_word_boundaries(self):
        texts = ["We reduced redundant work and updated the plan."]
        assert find_contradictions(texts, card(overall=Status.GREEN)) == []

    def test_yellow_means_amber(self):
        assert find_contradictions(["Budget is yellow."], card()) == []


# --- Figures ------------------------------------------------------------------------------


class TestFindDates:
    @pytest.mark.parametrize("text, reading", [
        ("due 2026-04-24", (4, 24)),
        ("due April 24, 2026", (4, 24)),
        ("due Apr 24th", (4, 24)),
        ("due 24 April 2026", (4, 24)),
        ("due Sept 14", (9, 14)),
    ])
    def test_formats(self, text, reading):
        dates, _ = find_dates(text)
        assert [r for _, r in dates] == [{reading}]

    @pytest.mark.parametrize("text", ["move weekend 12-13 December", "move weekend December 12–13",
                                      "move weekend 12 to 13 December 2026"])
    def test_day_ranges(self, text):
        dates, rest = find_dates(text)
        assert [r for _, r in dates] == [{(12, 12)}, {(12, 13)}]
        assert find_numbers(rest) == []

    def test_numeric_dates_are_ambiguous(self):
        dates, _ = find_dates("cutover 5/1")
        assert dates[0][1] == {(5, 1), (1, 5)}

    def test_dates_and_times_are_removed_before_numbers(self):
        _, rest = find_dates("Mar 12 2026 at 9:02 AM, 14 apps")
        assert [v for _, v in find_numbers(rest)] == [14]


class TestFindNumbers:
    @pytest.mark.parametrize("text, value", [
        ("$170K", 170_000), ("2.4M", 2_400_000), ("€1.29M", 1_290_000), ("$2,570,000", 2_570_000),
        ("2.57 million", 2_570_000), ("7.1%", 7.1), ("+32", 32), ("21 days", 21),
    ])
    def test_values(self, text, value):
        assert [v for _, v in find_numbers(text)] == [pytest.approx(value)]

    def test_small_bare_integers_are_ignored(self):
        assert find_numbers("2 cutovers and 6 sessions") == []

    def test_small_numbers_with_units_are_kept(self):
        assert [v for _, v in find_numbers("5% over")] == [5]
        assert [v for _, v in find_numbers("within 2 percent")] == [2]

    def test_words_with_digits_are_ignored(self):
        assert find_numbers("Q4 and v4") == []


class TestUnsupportedFigures:
    NOTES = "budgt 2.4M approved, forecast ~2.57M. cutover was 4/24 now 5/15. ask: $170K from contingency"

    def test_reformatted_figures_pass(self):
        texts = ["Forecast is $2,570,000 against $2.4 million.", "Cutover moved from 24 April to May 15.",
                 "Approve $170,000."]
        assert unsupported_figures(texts, [self.NOTES]) == []

    def test_rounding_passes(self):
        assert unsupported_figures(["About 7% over."], [self.NOTES, "Forecast vs plan (+7.1%)."]) == []

    def test_invented_figure_is_flagged(self):
        problems = unsupported_figures(["Forecast is $2.9M."], [self.NOTES])
        assert problems == ['Figure "$2.9M" isn\'t in the notes']

    def test_invented_date_is_flagged(self):
        assert unsupported_figures(["Cutover is now June 30."], [self.NOTES]) == ['Date "June 30" isn\'t in the notes']

    def test_small_bare_numbers_in_notes_count_as_sources(self):
        # Regression: "10%" in the output vs a bare "10" in a CSV % Complete column.
        assert unsupported_figures(["Huddle rooms 10% complete."], ["6,Huddle rooms,2026-10-05,10,No"]) == []

    def test_range_matches_separate_dates_in_notes(self):
        # Regression: "21-23 July" was flagged as an invented "21" in the first eval run.
        assert unsupported_figures(["Training 21-23 July."], ["Train night shift leads 7/21-7/23"]) == []

    def test_rule_reasons_count_as_sources(self):
        assert unsupported_figures(["It slipped 21 days."], [self.NOTES, "slipped 21 days"]) == []
