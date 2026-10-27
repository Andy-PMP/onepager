"""Handler and usage caps with fake AWS clients."""

import base64
import json
from datetime import UTC, datetime

import pytest
from test_pipeline import FACTS, GOOD_NARRATIVE, NOTES, FakeClient

from onepager import handler as handler_module
from onepager import limits

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


class ConditionalCheckFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamo:
    """Implements just the conditional ADD that limits.py uses."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def update_item(self, TableName, Key, ExpressionAttributeValues, **_):
        key, cap = Key["pk"]["S"], int(ExpressionAttributeValues[":cap"]["N"])
        item = self.items.setdefault(key, {"count": 0, "expires_at": int(ExpressionAttributeValues[":expires"]["N"])})
        if item["count"] >= cap:
            raise ConditionalCheckFailed()
        item["count"] += 1


# --- Caps ---------------------------------------------------------------------------------


def test_hash_is_salted_and_stable():
    assert limits.hash_ip("1.2.3.4", "salt-a") == limits.hash_ip("1.2.3.4", "salt-a")
    assert limits.hash_ip("1.2.3.4", "salt-a") != limits.hash_ip("1.2.3.4", "salt-b")
    assert "1.2.3.4" not in limits.hash_ip("1.2.3.4", "salt-a")


def test_visitor_cap():
    db = FakeDynamo()
    for _ in range(5):
        limits.consume(db, "t", "1.2.3.4", "s", 5, 100, NOW)
    with pytest.raises(limits.LimitReached) as e:
        limits.consume(db, "t", "1.2.3.4", "s", 5, 100, NOW)
    assert e.value.scope == "visitor"
    limits.consume(db, "t", "5.6.7.8", "s", 5, 100, NOW)  # another visitor is unaffected


def test_daily_cap():
    db = FakeDynamo()
    for i in range(3):
        limits.consume(db, "t", f"10.0.0.{i}", "s", 5, 3, NOW)
    with pytest.raises(limits.LimitReached) as e:
        limits.consume(db, "t", "10.0.0.9", "s", 5, 3, NOW)
    assert e.value.scope == "daily"
    assert str(e.value) == "Demo limit reached for today. Try a sample."


def test_visitor_over_cap_does_not_use_daily_budget():
    db = FakeDynamo()
    for _ in range(8):
        try:
            limits.consume(db, "t", "1.2.3.4", "s", 5, 100, NOW)
        except limits.LimitReached:
            pass
    assert db.items["daily#2026-10-27"]["count"] == 5


def test_keys_and_ttls():
    db = FakeDynamo()
    limits.consume(db, "t", "1.2.3.4", "s", 5, 100, NOW)
    visitor_key = next(k for k in db.items if k.startswith("visitor#"))
    assert visitor_key == f"visitor#2026-10-27#{limits.hash_ip('1.2.3.4', 's')}"
    assert "1.2.3.4" not in str(db.items)
    assert db.items[visitor_key]["expires_at"] == int(NOW.timestamp()) + 48 * 3600


def test_next_day_resets():
    db = FakeDynamo()
    for _ in range(5):
        limits.consume(db, "t", "1.2.3.4", "s", 5, 100, NOW)
    limits.consume(db, "t", "1.2.3.4", "s", 5, 100, datetime(2026, 10, 28, 0, 1, tzinfo=UTC))


# --- Handler ------------------------------------------------------------------------------


class Context:
    def get_remaining_time_in_millis(self):
        return 27_000


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "model")
    monkeypatch.setenv("TABLE_NAME", "usage")
    monkeypatch.setenv("IP_HASH_SALT", "test-salt")
    monkeypatch.setenv("PER_VISITOR_CAP", "5")
    monkeypatch.setenv("DAILY_CAP", "100")


def call(monkeypatch, body, bedrock=None, dynamo=None, ip="1.2.3.4", b64=False):
    bedrock = bedrock or FakeClient(FACTS, GOOD_NARRATIVE)
    dynamo = dynamo or FakeDynamo()
    monkeypatch.setattr(handler_module, "_clients", lambda: (bedrock, dynamo))
    raw = body if isinstance(body, str) else json.dumps(body)
    event = {"body": base64.b64encode(raw.encode()).decode() if b64 else raw, "isBase64Encoded": b64,
             "requestContext": {"http": {"sourceIp": ip, "method": "POST"}}}
    response = handler_module.handler(event, Context())
    return response["statusCode"], json.loads(response["body"])


def test_success(env, monkeypatch, capsys):
    status, body = call(monkeypatch, {"notes": NOTES})
    assert status == 200
    assert body["overall"] == "red" and "markdown" in body
    log = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert log["event"] == "generate" and log["ok"] is True
    assert set(log) >= {"ts", "chars", "input_tokens", "output_tokens", "latency_ms", "rules"}


def test_base64_body(env, monkeypatch):
    assert call(monkeypatch, {"notes": NOTES}, b64=True)[0] == 200


@pytest.mark.parametrize("body", ["not json", {"text": "x"}, {"notes": ""}, {"notes": "x" * 6001}, [1, 2]])
def test_bad_input_is_400_and_costs_nothing(env, monkeypatch, body):
    bedrock, dynamo = FakeClient(), FakeDynamo()
    status, payload = call(monkeypatch, body, bedrock, dynamo)
    assert status == 400 and payload["error"]
    assert bedrock.calls == [] and dynamo.items == {}


def test_cap_is_429_before_any_model_call(env, monkeypatch):
    dynamo = FakeDynamo()
    for _ in range(5):
        call(monkeypatch, {"notes": NOTES}, dynamo=dynamo)
    bedrock = FakeClient()
    status, payload = call(monkeypatch, {"notes": NOTES}, bedrock, dynamo)
    assert status == 429 and payload["limit"] == "visitor"
    assert bedrock.calls == []


def test_counter_failure_fails_closed(env, monkeypatch):
    class BrokenDynamo:
        def update_item(self, **_):
            raise RuntimeError("dynamo down")

    bedrock = FakeClient()
    status, _ = call(monkeypatch, {"notes": NOTES}, bedrock, BrokenDynamo())
    assert status == 503 and bedrock.calls == []


def test_pipeline_failure_is_502_and_log_has_no_text(env, monkeypatch, capsys):
    bad = {"headline": "Atlas is green. Forecast 999k."}
    bedrock = FakeClient({"risks": "none"}, {"risks": "none"})
    status, payload = call(monkeypatch, {"notes": NOTES}, bedrock)
    assert status == 502 and "try a sample" in payload["error"]
    out = capsys.readouterr().out
    assert '"stage": "extract retry"' in out
    assert NOTES not in out and "Atlas" not in out and bad["headline"] not in out


def test_logs_never_contain_notes_or_output(env, monkeypatch, capsys):
    call(monkeypatch, {"notes": NOTES})
    out = capsys.readouterr().out
    assert NOTES not in out
    assert "Atlas" not in out and GOOD_NARRATIVE["headline"] not in out
    assert "1.2.3.4" not in out
