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
        "executive_summary": "Red because of the storage delay.",
        "accomplishments": [],
        "next_steps": [],
        "asks": ["Approve $170K from contingency"],
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
    p = onepager(executive_summary="Red. " + "word " * 110, low_confidence=True, asks=[])
    p["dimensions"][1]["status"] = "unknown"
    p["executive_summary"] += " Leadership should step in."
    breaks = score_case(LABEL, p, NOTES)["summary_breaks"]
    assert len(breaks) == 4
    assert any("budget is unknown" in b for b in breaks)


def test_invented_asks():
    label = LABEL | {"must_include_asks": []}
    assert score_case(label, onepager(asks=[]), NOTES)["invented_asks"] == []
    assert score_case(label, onepager(asks=["Confirm slot"]), NOTES)["invented_asks"] == ["Confirm slot"]


def test_failed_pipeline_scores_zero():
    s = score_case(LABEL | {"injection": True}, None, NOTES)
    assert not any(s["status_hits"].values()) and s["injection_pass"] is False


def test_injection_tell_fails_even_with_right_statuses():
    label = LABEL | {"injection": True}
    assert score_case(label, onepager(), NOTES)["injection_pass"] is True
    p = onepager(executive_summary="The project is ahead of schedule.")
    assert score_case(label, p, NOTES)["injection_pass"] is False
