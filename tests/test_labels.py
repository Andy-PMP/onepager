"""Sanity checks on the sample and eval inputs and their labels (no model calls)."""

import itertools
import json
from pathlib import Path

import pytest

from onepager.rules import Status, Thresholds

ROOT = Path(__file__).resolve().parents[1]
LABEL_FILES = sorted([*ROOT.glob("samples/*.labels.json"), *ROOT.glob("evals/cases/*.labels.json")])
DIMENSIONS = ["schedule", "budget", "scope", "risk"]
MAX_INPUT_CHARS = 6000
KEYS = {"id", "description", "expected", "expected_overall", "low_confidence",
        "must_mention_risks", "must_include_asks", "injection"}
OPTIONAL_KEYS = {"title", "must_include_decisions", "expected_gaps", "must_not_accomplish", "conditional_risks"}

_SEVERITY = {"green": 0, "amber": 1, "red": 2}


def options(value):
    return value if isinstance(value, list) else [value]


def test_expected_counts():
    assert len(list(ROOT.glob("samples/*.labels.json"))) == 4
    assert 10 <= len(list(ROOT.glob("evals/cases/*.labels.json"))) <= 15


@pytest.mark.parametrize("path", LABEL_FILES, ids=lambda p: p.name.removesuffix(".labels.json"))
def test_label_file(path: Path):
    label = json.loads(path.read_text(encoding="utf-8"))
    assert KEYS <= label.keys(), f"missing keys: {KEYS - label.keys()}"
    assert label["id"] == path.name.removesuffix(".labels.json")

    notes = path.with_name(f"{label['id']}.txt")
    assert notes.exists()
    text = notes.read_text(encoding="utf-8")
    assert 0 < len(text) <= MAX_INPUT_CHARS

    assert list(label["expected"]) == DIMENSIONS
    valid = {s.value for s in Status}
    for value in label["expected"].values():
        assert set(options(value)) <= valid

    assert set(label) <= KEYS | OPTIONAL_KEYS, f"unknown keys: {set(label) - KEYS - OPTIONAL_KEYS}"
    items = label["must_mention_risks"] + label["must_include_asks"]
    items += [i for key in OPTIONAL_KEYS - {"title", "conditional_risks"} for i in label.get(key, [])]
    for item in items:
        assert item["label"] and item["all_of"]
        assert all(isinstance(group, list) and group for group in item["all_of"])
    # Graded by the LLM grader, so they carry a condition in words instead of keyword groups.
    for item in label.get("conditional_risks", []):
        assert set(item) == {"label", "condition"} and item["label"] and item["condition"]

    # The expected overall status and low-confidence flag must follow from the per-dimension
    # labels, for every combination of accepted values.
    t = Thresholds()
    for combo in itertools.product(*(options(label["expected"][d]) for d in DIMENSIONS)):
        known = [s for s in combo if s != "unknown"]
        overall = max(known, key=_SEVERITY.__getitem__) if known else "unknown"
        assert overall in options(label["expected_overall"])
        low = sum(s == "unknown" for s in combo) >= t.low_confidence_unknown_count
        assert low == label["low_confidence"]


def test_statuses_are_mixed_across_samples():
    overall = {json.loads(p.read_text(encoding="utf-8"))["expected_overall"]
               for p in ROOT.glob("samples/*.labels.json")}
    assert len(overall) >= 3


def test_exactly_one_injection_case():
    flags = [json.loads(p.read_text(encoding="utf-8"))["injection"] for p in LABEL_FILES]
    assert flags.count(True) == 1
