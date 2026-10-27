"""The facts the extraction step pulls out of the notes, and how they are validated.

Convention: a field the notes don't mention is None. For lists, None means "not mentioned"
and [] means "the notes say there are none" (e.g. "no scope changes this period"). The
scoring rules depend on that difference to tell Unknown from Green.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

SCOPE_STATUSES = ("approved", "pending", "rejected")
RISK_KINDS = ("risk", "issue")
IMPACTS = ("high", "medium", "low")
RISK_STATES = ("open", "closed")


class SchemaError(ValueError):
    """The extracted JSON doesn't match the schema."""


@dataclass(frozen=True)
class Milestone:
    name: str
    planned_date: date | None = None
    forecast_date: date | None = None
    actual_date: date | None = None
    is_critical: bool | None = None
    recovery_plan: str | None = None


@dataclass(frozen=True)
class UnforecastCost:
    description: str
    amount: float | None = None


@dataclass(frozen=True)
class Budget:
    planned: float | None = None
    actual: float | None = None
    forecast: float | None = None
    currency: str | None = None
    # Costs the notes say aren't in the forecast yet. Reported as a gap; they don't change the status.
    unforecast_costs: list[UnforecastCost] = field(default_factory=list)


@dataclass(frozen=True)
class ScopeChange:
    description: str
    status: str | None = None
    affected_milestone: str | None = None
    impact_estimate: str | None = None
    # 3-6 words ("CR-9 audit dashboard"), used in reasons and gaps where the description is too long.
    title: str | None = None


@dataclass(frozen=True)
class Risk:
    description: str
    title: str | None = None
    kind: str | None = None
    impact: str | None = None
    owner: str | None = None
    mitigation: str | None = None
    state: str | None = None
    # When the notes say it will be resolved or decided, as written ("by Monday", "2026-11-15").
    resolve_by: str | None = None
    # What has to happen first for a risk to hit ("if go-live slips past February"). Kept separate so the
    # summary can't present a possibility as something already happening.
    condition: str | None = None


@dataclass(frozen=True)
class Facts:
    project_name: str | None = None
    # No reporting period: the model kept inventing one ("week ending" a Monday), so the page shows
    # "As of <as_of_date>", built in code.
    as_of_date: date | None = None
    milestones: list[Milestone] | None = None
    budget: Budget | None = None
    scope_changes: list[ScopeChange] | None = None
    risks: list[Risk] | None = None
    accomplishments: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)
    open_decisions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


# --- JSON Schema handed to the model as the extraction tool's input schema ---------------

_STR = {"type": ["string", "null"]}
_DATE = {"type": ["string", "null"], "description": "YYYY-MM-DD, only if the notes give a specific date"}
_NUM = {"type": ["number", "null"]}
_TITLE = {"type": ["string", "null"]}


def _enum(values: tuple[str, ...]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None]}


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


EXTRACTION_JSON_SCHEMA: dict[str, Any] = _obj(
    {
        "project_name": _STR,
        "as_of_date": {**_DATE, "description": "Date of the notes or report, YYYY-MM-DD"},
        "milestones": {
            "type": ["array", "null"],
            "description": "null if the notes don't discuss milestones or dates",
            "items": _obj(
                {
                    "name": {"type": "string"},
                    "planned_date": _DATE,
                    "forecast_date": {**_DATE, "description": "Current expected date if it differs or is restated"},
                    "actual_date": {**_DATE, "description": "Completion date, if completed"},
                    "is_critical": {"type": ["boolean", "null"]},
                    "recovery_plan": _STR,
                },
                ["name"],
            ),
        },
        "budget": {
            "anyOf": [
                {"type": "null"},
                _obj(
                    {
                        "planned": _NUM,
                        "actual": _NUM,
                        "forecast": _NUM,
                        "currency": _STR,
                        "unforecast_costs": {
                            "type": "array",
                            "description": "Costs the notes say are NOT yet included in the forecast",
                            "items": _obj({"description": {"type": "string"}, "amount": _NUM}, ["description"]),
                        },
                    },
                    [],
                ),
            ],
            "description": "null if the notes give no budget figures. Never estimate numbers.",
        },
        "scope_changes": {
            "type": ["array", "null"],
            "description": "null if scope isn't mentioned; [] if the notes say there are no changes",
            "items": _obj(
                {
                    "title": {**_TITLE, "description": "3-6 word title, e.g. \"CR-9 audit dashboard\""},
                    "description": {"type": "string"},
                    "status": _enum(SCOPE_STATUSES),
                    "affected_milestone": {**_STR, "description": "Exact name from milestones, if any"},
                    "impact_estimate": {
                        **_STR,
                        "description": "The cost or schedule estimate the notes give for this change "
                                       "(an amount, a number of days, a new date); null if none is given",
                    },
                },
                ["description"],
            ),
        },
        "risks": {
            "type": ["array", "null"],
            "description": "Risks and issues. null if not mentioned; [] if the notes say there are none",
            "items": _obj(
                {
                    "title": {**_TITLE, "description": "3-6 word title, e.g. \"Badge printer shortage\""},
                    "description": {"type": "string"},
                    "kind": _enum(RISK_KINDS),
                    "impact": _enum(IMPACTS),
                    "owner": _STR,
                    "mitigation": _STR,
                    "state": _enum(RISK_STATES),
                    "resolve_by": {
                        **_STR,
                        "description": "When the notes say it will be resolved or decided, as written "
                                       "(\"by Monday\", YYYY-MM-DD); null if no timing is given",
                    },
                    "condition": {
                        **_STR,
                        "description": "What has to happen first for the risk to hit, as the notes state it "
                                       "(\"if the vendor misses the March delivery\"); null if none is stated",
                    },
                },
                ["description"],
            ),
        },
        "accomplishments": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "asks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only decisions or requests the notes explicitly direct at leadership, a sponsor or a "
                           "steering committee. A team member asking a vendor or colleague something is not an "
                           "ask. Often empty.",
        },
        "open_decisions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Choices the notes say are still undecided (tbd, open question, need to decide), "
                           "that aren't already in asks. Not questions put to vendors or colleagues. Often empty.",
        },
    },
    ["accomplishments", "next_steps", "asks"],
)


# --- Parsing ------------------------------------------------------------------------------


def parse_facts(data: Any) -> Facts:
    """Validate extracted JSON and convert it to Facts. Raises SchemaError on any mismatch."""
    obj = _expect_obj(data, "facts", Facts)
    budget = obj.get("budget")
    return Facts(
        project_name=_opt_str(obj, "project_name", "facts"),
        as_of_date=_opt_date(obj, "as_of_date", "facts"),
        milestones=_opt_list(obj, "milestones", _milestone),
        budget=None if budget is None else _budget(budget),
        scope_changes=_opt_list(obj, "scope_changes", _scope_change),
        risks=_opt_list(obj, "risks", _risk),
        accomplishments=_str_list(obj, "accomplishments"),
        next_steps=_str_list(obj, "next_steps"),
        asks=_str_list(obj, "asks"),
        open_decisions=_str_list(obj, "open_decisions"),
    )


def _milestone(data: Any, where: str) -> Milestone:
    obj = _expect_obj(data, where, Milestone)
    critical = obj.get("is_critical")
    if critical is not None and not isinstance(critical, bool):
        raise SchemaError(f"{where}.is_critical must be true, false or null")
    return Milestone(
        name=_req_str(obj, "name", where),
        planned_date=_opt_date(obj, "planned_date", where),
        forecast_date=_opt_date(obj, "forecast_date", where),
        actual_date=_opt_date(obj, "actual_date", where),
        is_critical=critical,
        recovery_plan=_opt_str(obj, "recovery_plan", where),
    )


def _budget(data: Any) -> Budget:
    obj = _expect_obj(data, "budget", Budget)
    return Budget(
        planned=_opt_num(obj, "planned", "budget"),
        actual=_opt_num(obj, "actual", "budget"),
        forecast=_opt_num(obj, "forecast", "budget"),
        currency=_opt_str(obj, "currency", "budget"),
        unforecast_costs=_opt_list(obj, "unforecast_costs", _unforecast_cost) or [],
    )


def _unforecast_cost(data: Any, where: str) -> UnforecastCost:
    obj = _expect_obj(data, where, UnforecastCost)
    return UnforecastCost(description=_req_str(obj, "description", where), amount=_opt_num(obj, "amount", where))


def _scope_change(data: Any, where: str) -> ScopeChange:
    obj = _expect_obj(data, where, ScopeChange)
    return ScopeChange(
        description=_req_str(obj, "description", where),
        status=_opt_enum(obj, "status", where, SCOPE_STATUSES),
        affected_milestone=_opt_str(obj, "affected_milestone", where),
        impact_estimate=_opt_str(obj, "impact_estimate", where),
        title=_opt_str(obj, "title", where),
    )


def _risk(data: Any, where: str) -> Risk:
    obj = _expect_obj(data, where, Risk)
    return Risk(
        description=_req_str(obj, "description", where),
        title=_opt_str(obj, "title", where),
        kind=_opt_enum(obj, "kind", where, RISK_KINDS),
        impact=_opt_enum(obj, "impact", where, IMPACTS),
        owner=_opt_str(obj, "owner", where),
        mitigation=_opt_str(obj, "mitigation", where),
        state=_opt_enum(obj, "state", where, RISK_STATES),
        resolve_by=_opt_str(obj, "resolve_by", where),
        condition=_opt_str(obj, "condition", where),
    )


def _expect_obj(data: Any, where: str, cls: type) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError(f"{where} must be an object")
    unknown = set(data) - set(cls.__dataclass_fields__)
    if unknown:
        raise SchemaError(f"{where} has unknown fields: {', '.join(sorted(unknown))}")
    return data


def _req_str(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _opt_str(obj: dict[str, Any], key: str, where: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"{where}.{key} must be a string or null")
    return value.strip() or None


def _opt_num(obj: dict[str, Any], key: str, where: str) -> float | None:
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SchemaError(f"{where}.{key} must be a number or null")
    return float(value)


def _opt_date(obj: dict[str, Any], key: str, where: str) -> date | None:
    value = _opt_str(obj, key, where)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SchemaError(f"{where}.{key} must be YYYY-MM-DD, got {value!r}") from None


def _opt_enum(obj: dict[str, Any], key: str, where: str, allowed: tuple[str, ...]) -> str | None:
    value = _opt_str(obj, key, where)
    if value is not None and value not in allowed:
        raise SchemaError(f"{where}.{key} must be one of {', '.join(allowed)} or null")
    return value


def _opt_list(obj: dict[str, Any], key: str, parse) -> list | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise SchemaError(f"{key} must be a list or null")
    return [parse(item, f"{key}[{i}]") for i, item in enumerate(value)]


def _str_list(obj: dict[str, Any], key: str) -> list[str]:
    value = obj.get(key)
    if value is None:
        return []
    if isinstance(value, str):  # a single item sent without the list; not worth a retry
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SchemaError(f"{key} must be a list of strings")
    return [v.strip() for v in value if v.strip()]
