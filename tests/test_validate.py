import pytest

from onepager.rules import RuleResult, Scorecard, Status
from onepager.schema import SchemaError
from onepager.validate import (
    find_contradictions,
    find_dates,
    find_numbers,
    headline_style_problems,
    invented_connectives,
    parse_headline,
    unsupported_attributions,
    unsupported_figures,
)


def card(overall=Status.RED, **dims):
    statuses = {"schedule": Status.RED, "budget": Status.AMBER, "scope": Status.GREEN, "risk": Status.AMBER} | dims
    results = [RuleResult(d, s, f"{d}.x", "reason") for d, s in statuses.items()]
    return Scorecard(results, overall, "Worst known dimension.", False, [])


# --- Headline shape -----------------------------------------------------------------------


def test_parses_headline():
    assert parse_headline({"headline": "  Go-live is three weeks late.  "}) == "Go-live is three weeks late."


@pytest.mark.parametrize("data, message", [
    ({"headline": ""}, "non-empty"),
    ({"headline": "x" * 500}, "longer"),
    ({"headline": 3}, "non-empty"),
    ({"headline": "ok", "accomplishments": []}, "only headline"),
    # The garbled tool output seen from Haiku 4.5 in testing
    ({"headline": "\n<item>Wave 1 done</item>\n</invoke>"}, "markup"),
    ("Late.", "only headline"),
])
def test_rejects_bad_headline(data, message):
    with pytest.raises(SchemaError, match=message):
        parse_headline(data)


@pytest.mark.parametrize("headline, has_asks, expected", [
    ("Go-live is three weeks late and nobody owns the firmware fix.", True, []),
    ("Go-live is late. Budget is over.", True, ["Write exactly one sentence"]),
    ("Schedule is red and budget is amber.", True,
     ["The sentence names status colours (amber, red); describe the problem instead"]),
    ("Leadership must step in on the late go-live.", False,
     ["The sentence suggests a leadership action, but there are no asks"]),
    (" ".join(["word"] * 31) + ".", True, ["The sentence is 31 words; keep it to 30"]),
])
def test_headline_style(headline, has_asks, expected):
    assert headline_style_problems(headline, has_asks) == expected


def test_headline_that_repeats_the_facts_is_rewritten():
    # From the WMS output: the headline restated the code-built sentence right after it.
    facts = ("Raleigh DC go-live slipped 21 days to 2027-02-01, and high-impact risk Handheld scanner firmware "
             "certification has no owner and mitigation.")
    repeat = "Raleigh DC go-live slipped to 2027-02-01, and scanner firmware certification lacks an owner."
    takeaway = "Go-live is three weeks late and nobody owns the fix pickers need at launch."
    assert any("repeats the facts" in p for p in headline_style_problems(repeat, True, facts))
    assert headline_style_problems(takeaway, True, facts) == []


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


# --- Attributions -------------------------------------------------------------------------

WMS_NOTES = ("submitted to steering. need steering to approve or defer CR-14 by Nov 7. "
             "need approval for weekend overtime for cutover. Priya to model the overtime. Keisha covering.")
WMS_ASKS = ["Steering to approve or defer CR-14 by 7 November", "Approval for weekend overtime for cutover"]


class TestAttributions:
    def test_approver_borrowed_from_another_ask_is_flagged(self):
        # The exact problem from the review: steering approves CR-14, but nobody is named for the overtime.
        summary = "Steering approval is needed for CR-14 by 7 November and for weekend overtime for cutover."
        problems = unsupported_attributions(summary, WMS_ASKS, WMS_NOTES)
        assert problems == ['Says "steering" for "Approval for weekend overtime for cutover", '
                            "but the notes don't say who approves that"]

    @pytest.mark.parametrize("summary", [
        "Steering must decide on CR-14 by 7 November, and approval is needed for weekend overtime.",
        "Approval is needed for weekend overtime for cutover; steering must decide on CR-14.",
        "CR-14 needs a steering decision by 7 November. Weekend overtime for cutover also needs approval.",
    ])
    def test_correct_attribution_passes(self, summary):
        assert unsupported_attributions(summary, WMS_ASKS, WMS_NOTES) == []

    def test_role_placed_after_both_items_is_flagged(self):
        summary = "CR-14 and weekend overtime for cutover both need steering approval."
        assert len(unsupported_attributions(summary, WMS_ASKS, WMS_NOTES)) == 1

    def test_role_not_in_notes_is_flagged(self):
        assert unsupported_attributions("The sponsor must approve the overtime.", WMS_ASKS, WMS_NOTES) == [
            '"sponsor" isn\'t named in the notes']

    def test_steering_aliases_and_clause_starts(self):
        # From eval runs: "steering committee" vs notes' "steering", and "Send" after a semicolon.
        summary = "The steering committee must approve or defer CR-14 by 7 November; Send the plan Friday."
        assert unsupported_attributions(summary, WMS_ASKS, WMS_NOTES) == []

    def test_abbreviated_words_are_not_invented_names(self):
        # From an eval run: "Executive all-hands" when the notes said "exec all-hands".
        notes = "we need the exec all-hands announcement of the go-live date"
        assert unsupported_attributions("Leadership should send the Executive all-hands note.", [], notes) == []

    def test_invented_person_is_flagged_but_names_from_notes_and_months_pass(self):
        summary = "Approval is needed by 7 November from Raj, and Priya will model the overtime with Keisha."
        assert unsupported_attributions(summary, WMS_ASKS, WMS_NOTES) == ['Name "Raj" isn\'t in the notes']


class TestConnectives:
    NOTES = "if go-live slips past February we hit the inventory count. overage mostly vendor fees bc of the delay"

    def test_invented_link_is_flagged(self):
        # The sentence from the WMS review.
        summary = ("Go-live slipped to 1 February, creating risk of collision; a no-go decision is required by "
                   "15 January to avoid April fallback.")
        problems = invented_connectives(summary, self.NOTES)
        assert [p.split('"')[1] for p in problems] == ["creating", "to avoid"]

    def test_prevent_is_a_link_too(self):
        # From the final eval: the WMS rewrite said "require immediate attention to prevent spring inventory conflict".
        assert invented_connectives("Go-live needs attention to prevent an inventory clash.", self.NOTES) == [
            'The summary links facts with "to prevent", which the notes don\'t; state the facts side by side instead']

    def test_facts_side_by_side_pass(self):
        summary = "Go-live slipped to 1 February; if it slips past February it hits the inventory count."
        assert invented_connectives(summary, self.NOTES) == []

    def test_a_link_the_notes_make_is_allowed(self):
        assert invented_connectives("The overrun is because of vendor fees.", "over budget because of vendor fees") \
            == []


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
