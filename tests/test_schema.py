import json
import re
from datetime import date

import pytest

from onepager.schema import EXTRACTION_JSON_SCHEMA, Facts, SchemaError, parse_facts

VALID = {
    "project_name": "Atlas DC Migration",
    "as_of_date": "2026-06-05",
    "milestones": [
        {"name": "Cutover", "planned_date": "2026-06-20", "forecast_date": "2026-07-10", "is_critical": True},
    ],
    "budget": {"planned": 1200000, "actual": None, "forecast": 1310000.5, "currency": "USD",
               "unforecast_costs": [{"description": "Overtime", "amount": 18000}, {"description": "Legal"}]},
    "scope_changes": [{"description": "Add DR site", "status": "pending", "affected_milestone": "Cutover",
                       "impact_estimate": "$40K"}],
    "risks": [{"title": "Vendor delivery delay", "description": "Vendor late", "kind": "risk", "impact": "high",
               "owner": "Sam", "mitigation": None, "resolve_by": "by Friday"}],
    "accomplishments": ["Racked servers"],
    "next_steps": ["Test failover"],
    "asks": ["Approve DR budget"],
    "open_decisions": ["Absorb the overage or push back on the vendor"],
}


def test_parses_valid_facts():
    f = parse_facts(VALID)
    assert f.as_of_date == date(2026, 6, 5)
    assert f.milestones[0].forecast_date == date(2026, 7, 10)
    assert f.milestones[0].is_critical is True
    assert f.budget.forecast == 1310000.5
    assert f.scope_changes[0].status == "pending"
    assert f.scope_changes[0].impact_estimate == "$40K"
    assert f.risks[0].mitigation is None
    assert f.risks[0].resolve_by == "by Friday"
    assert f.risks[0].title == "Vendor delivery delay"
    assert [(c.description, c.amount) for c in f.budget.unforecast_costs] == [("Overtime", 18000), ("Legal", None)]
    assert f.open_decisions == ["Absorb the overage or push back on the vendor"]


def test_single_string_is_accepted_as_a_one_item_list():
    # Seen from the model on the very-short case; cheaper to accept than to retry.
    f = parse_facts({"accomplishments": [], "next_steps": "More next week", "asks": []})
    assert f.next_steps == ["More next week"]


def test_new_fields_default_to_empty():
    f = parse_facts({"budget": {"planned": 1}, "accomplishments": [], "next_steps": [], "asks": []})
    assert f.budget.unforecast_costs == [] and f.open_decisions == []


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
        ({"budget": {"unforecast_costs": [{"amount": 5}]}}, "unforecast_costs[0].description"),
        ({"budget": {"unforecast_costs": [{"description": "x", "amount": "5k"}]}}, "unforecast_costs[0].amount"),
        ({"open_decisions": [1]}, "open_decisions"),
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
