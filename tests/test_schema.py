import json
import re
from datetime import date

import pytest

from onepager.schema import EXTRACTION_JSON_SCHEMA, Facts, SchemaError, parse_facts

VALID = {
    "project_name": "Atlas DC Migration",
    "reporting_period": "Week of 1 June 2026",
    "as_of_date": "2026-06-05",
    "milestones": [
        {"name": "Cutover", "planned_date": "2026-06-20", "forecast_date": "2026-07-10", "is_critical": True},
    ],
    "budget": {"planned": 1200000, "actual": None, "forecast": 1310000.5, "currency": "USD"},
    "scope_changes": [{"description": "Add DR site", "status": "pending", "affected_milestone": "Cutover"}],
    "risks": [{"description": "Vendor late", "kind": "risk", "impact": "high", "owner": "Sam", "mitigation": None}],
    "accomplishments": ["Racked servers"],
    "next_steps": ["Test failover"],
    "asks": ["Approve DR budget"],
}


def test_parses_valid_facts():
    f = parse_facts(VALID)
    assert f.as_of_date == date(2026, 6, 5)
    assert f.milestones[0].forecast_date == date(2026, 7, 10)
    assert f.milestones[0].is_critical is True
    assert f.budget.forecast == 1310000.5
    assert f.scope_changes[0].status == "pending"
    assert f.risks[0].mitigation is None


def test_round_trips_through_to_dict():
    assert parse_facts(parse_facts(VALID).to_dict()) == parse_facts(VALID)


def test_minimal_input_keeps_null_vs_empty_distinction():
    f = parse_facts({"accomplishments": [], "next_steps": [], "asks": [], "risks": []})
    assert f == Facts(risks=[])
    assert f.milestones is None and f.scope_changes is None and f.budget is None


def test_blank_strings_become_none_and_lists_are_trimmed():
    f = parse_facts({"project_name": "  ", "accomplishments": [" a ", ""], "next_steps": [], "asks": []})
    assert f.project_name is None
    assert f.accomplishments == ["a"]


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"as_of_date": "Q3 2026"}, "YYYY-MM-DD"),
        ({"budget": {"planned": "1.2M"}}, "budget.planned"),
        ({"budget": {"planned": True}}, "budget.planned"),
        ({"milestones": [{"name": ""}]}, "milestones[0].name"),
        ({"milestones": [{"name": "x", "is_critical": "yes"}]}, "is_critical"),
        ({"risks": [{"description": "x", "impact": "severe"}]}, "risks[0].impact"),
        ({"scope_changes": [{"description": "x", "status": "maybe"}]}, "status"),
        ({"risks": "none"}, "risks must be a list"),
        ({"asks": [1, 2]}, "asks"),
        ({"overall_status": "green"}, "unknown fields"),
        ({"milestones": [{"name": "x", "slip": 3}]}, "unknown fields"),
    ],
)
def test_rejects_invalid(patch, message):
    with pytest.raises(SchemaError, match=re.escape(message)):
        parse_facts({**VALID, **patch})


def test_rejects_non_object():
    with pytest.raises(SchemaError):
        parse_facts([VALID])


def test_json_schema_covers_every_field():
    assert set(EXTRACTION_JSON_SCHEMA["properties"]) == set(Facts.__dataclass_fields__)
    json.dumps(EXTRACTION_JSON_SCHEMA)  # serializable for the Bedrock tool spec
