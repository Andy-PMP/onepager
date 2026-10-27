"""The grader's plumbing with a fake client: how its answers are read, not how good its judgment is
(grader_calibration.json covers that against the real model on every eval run)."""

import json
from pathlib import Path

from grader import grade
from onepager.bedrock import Usage

RISKS = [{"label": "Peak season collision", "condition": "only if go-live slips past February"},
         {"label": "Fallback to legacy", "condition": "one outcome of the no-go decision"}]


class FakeClient:
    def __init__(self, answer):
        self.answer = answer
        self.sent = None

    def converse(self, **kwargs):
        self.sent = kwargs["messages"][0]["content"][0]["text"]
        return {"output": {"message": {"content": [{"toolUse": {"name": "record_grades", "input": self.answer}}]}},
                "stopReason": "tool_use", "usage": {"inputTokens": 10, "outputTokens": 5}}


def test_reads_grades_and_unsupported_links():
    client = FakeClient({
        "causal_phrases": [{"quote": "creating risk of collision", "supported": False, "why": "conditional"},
                           {"quote": "because the vendor is late", "supported": True, "why": "notes say so"}],
        "conditional_risks": [
            {"summary_quote": "creating risk of collision", "presented_as": "happening_or_certain", "why": "x"},
            {"summary_quote": None, "presented_as": "not_mentioned", "why": "absent"}]})
    result = grade(client, "m", "notes", "summary", RISKS, Usage())
    assert [g["correct"] for g in result["conditional_risks"]] == [False, True]
    assert result["invented_links"] == ["creating risk of collision"]
    assert "1. Peak season collision: only if go-live slips past February" in client.sent


def test_a_risk_the_grader_skipped_counts_as_failed():
    result = grade(FakeClient({"causal_phrases": [], "conditional_risks": []}), "m", "n", "s", RISKS, Usage())
    assert [g["correct"] for g in result["conditional_risks"]] == [False, False]
    assert result["conditional_risks"][0]["reason"] == "not graded"


def test_cases_without_conditional_risks_still_get_the_link_check():
    client = FakeClient({"causal_phrases": [], "conditional_risks": []})
    assert grade(client, "m", "n", "s", [], Usage()) == {"conditional_risks": [], "invented_links": []}
    assert "(none)" in client.sent


def test_calibration_file_has_a_bad_and_a_good_example_with_real_notes():
    cases = json.loads((Path(__file__).parent / "grader_calibration.json").read_text(encoding="utf-8"))
    assert {c["expect"]["conditional_correct"][0] for c in cases} == {True, False}
    for c in cases:
        assert (Path(__file__).parent / c["notes"]).exists()
        assert len(c["expect"]["conditional_correct"]) == len(c["conditional_risks"])
        assert c["summary"].startswith(c["headline"])  # the headline is the summary's first sentence
