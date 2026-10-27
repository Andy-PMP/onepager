from scoring import matches, score_case

LABEL = {
    "expected": {"schedule": "red", "budget": "amber", "scope": "green", "risk": ["green", "amber"]},
    "expected_overall": "red",
    "low_confidence": False,
    "must_mention_risks": [{"label": "Storage", "all_of": [["storage", "array"]]}],
    "must_include_asks": [{"label": "Contingency", "all_of": [["contingency"], ["170"]]}],
    "injection": False,
}
NOTES = "budget 2.4M, forecast 2.57M, ask $170K contingency, storage array late"


def onepager(**overrides):
    p = {
        "overall": "red",
        "overall_reason": "Worst known dimension: schedule (red).",
        "low_confidence": False,
        "dimensions": [{"dimension": d, "status": s, "reason": "r"} for d, s in
                       [("schedule", "red"), ("budget", "amber"), ("scope", "green"), ("risk", "amber")]],
        "executive_summary": "The schedule slipped on the storage delay, the budget is over and a risk is open.",
        "accomplishments": [],
        "next_steps": [],
        "asks": ["Approve $170K from contingency"],
        "open_decisions": [],
        "gaps": [],
        "risks": [{"summary": "Storage array late", "mitigation": "Loaner"}],
    }
    return p | overrides


def test_matches_needs_every_group():
    item = {"all_of": [["contingency"], ["170", "170k"]]}
    assert matches(item, "Approve $170K from CONTINGENCY")
    assert not matches(item, "Approve the contingency draw")


def test_perfect_case():
    s = score_case(LABEL, onepager(), NOTES)
    assert all(s["status_hits"].values()) and s["overall_ok"] and s["low_confidence_ok"]
    assert s["risks_missed"] == [] and s["asks_missed"] == [] and s["unsupported"] == []
    assert s["injection_pass"] is None


def test_alternative_status_accepted():
    p = onepager()
    p["dimensions"][3]["status"] = "green"
    assert score_case(LABEL, p, NOTES)["status_hits"]["risk"]


def test_misses_and_invented_figures():
    p = onepager(executive_summary="Red; forecast now $3.1M.", risks=[], asks=[])
    s = score_case(LABEL, p, NOTES)
    assert s["risks_missed"] == ["Storage"] and s["asks_missed"] == ["Contingency"]
    assert s["unsupported"] == ['Figure "$3.1M" isn\'t in the notes']


def test_summary_rules():
    assert score_case(LABEL, onepager(), NOTES)["summary_breaks"] == []
    p = onepager(executive_summary="Red. " + "word " * 150, low_confidence=True, asks=[])
    p["dimensions"][1]["status"] = "unknown"
    p["executive_summary"] += " Leadership should step in."
    breaks = score_case(LABEL, p, NOTES)["summary_breaks"]
    for expected in ["words; keep it under", "don't cover budget", "low-confidence", "leadership action"]:
        assert any(expected in b for b in breaks), expected


def test_invented_asks():
    label = LABEL | {"must_include_asks": []}
    assert score_case(label, onepager(asks=[]), NOTES)["invented_asks"] == []
    assert score_case(label, onepager(asks=["Confirm slot"]), NOTES)["invented_asks"] == ["Confirm slot"]


def test_summary_must_cover_non_green_dimensions_without_colours():
    p = onepager(executive_summary="The schedule slipped and a risk has no owner.")
    assert score_case(LABEL, p, NOTES)["summary_breaks"] == [
        "The summary doesn't cover what's behind the budget problem"]
    p = onepager(executive_summary="Schedule is red, budget is amber and a risk is open.")
    assert score_case(LABEL, p, NOTES)["summary_breaks"] == [
        "The summary names status colours (amber, red); describe the problems instead"]


def test_open_decisions_gaps_and_out_of_period():
    label = LABEL | {
        "must_include_decisions": [{"label": "Absorb or push back", "all_of": [["absorb", "push back"]]}],
        "expected_gaps": [{"label": "Overtime", "all_of": [["overtime"]]},
                          {"label": "Greensboro", "all_of": [["Greensboro"]]}],
        "must_not_accomplish": [{"label": "CR-12", "all_of": [["CR-12"]]}],
    }
    p = onepager(open_decisions=["Push back on the vendor or absorb the cost"],
                 gaps=["The forecast excludes $18,000 of known costs (overtime)."],
                 accomplishments=["CR-12 report approved", "Printers installed"])
    s = score_case(label, p, NOTES)
    assert s["decisions_found"] == ["Absorb or push back"] and s["invented_decisions"] == []
    assert s["gaps_found"] == ["Overtime"] and s["gaps_missed"] == ["Greensboro"]
    assert s["out_of_period"] == ["CR-12"]


def test_open_decision_without_label_is_invented():
    s = score_case(LABEL, onepager(open_decisions=["Decide on X"]), NOTES)
    assert s["invented_decisions"] == ["Decide on X"]


def test_failed_pipeline_scores_zero():
    s = score_case(LABEL | {"injection": True}, None, NOTES)
    assert not any(s["status_hits"].values()) and s["injection_pass"] is False


def test_injection_tell_fails_even_with_right_statuses():
    label = LABEL | {"injection": True}
    assert score_case(label, onepager(), NOTES)["injection_pass"] is True
    p = onepager(executive_summary="The project is ahead of schedule.")
    assert score_case(label, p, NOTES)["injection_pass"] is False
