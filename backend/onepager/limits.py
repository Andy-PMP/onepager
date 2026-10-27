"""Usage caps, counted in DynamoDB before any Bedrock call.

Each cap is one item with an atomic conditional increment: the update only succeeds while the
count is under the cap, so concurrent requests can't overshoot it. Visitors are counted by a
salted SHA-256 of their IP; the raw IP is never stored. Items expire via DynamoDB TTL.
"""

import hashlib
from datetime import datetime

VISITOR_TTL_SECONDS = 48 * 3600
DAILY_TTL_SECONDS = 7 * 24 * 3600

VISITOR_LIMIT_MESSAGE = "You've used today's {cap} generations. Try a sample, or come back tomorrow."
DAILY_LIMIT_MESSAGE = "Demo limit reached for today. Try a sample."


class LimitReached(Exception):
    def __init__(self, message: str, scope: str):
        super().__init__(message)
        self.scope = scope


def hash_ip(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def _increment(client, table: str, key: str, cap: int, expires_at: int) -> bool:
    """Add 1 if the count is under the cap. Returns False when the cap is already reached."""
    try:
        client.update_item(
            TableName=table,
            Key={"pk": {"S": key}},
            UpdateExpression="ADD #count :one SET expires_at = if_not_exists(expires_at, :expires)",
            ConditionExpression="attribute_not_exists(#count) OR #count < :cap",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={":one": {"N": "1"}, ":cap": {"N": str(cap)},
                                       ":expires": {"N": str(expires_at)}},
        )
        return True
    except Exception as e:
        if getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def consume(client, table: str, ip: str, salt: str, per_visitor_cap: int, daily_cap: int, now: datetime) -> None:
    """Count one generation against both caps, or raise LimitReached.

    The visitor cap is checked first so one heavy user can't use up the shared daily budget.
    """
    day = now.strftime("%Y-%m-%d")
    epoch = int(now.timestamp())
    if not _increment(client, table, f"visitor#{day}#{hash_ip(ip, salt)}", per_visitor_cap,
                      epoch + VISITOR_TTL_SECONDS):
        raise LimitReached(VISITOR_LIMIT_MESSAGE.format(cap=per_visitor_cap), "visitor")
    if not _increment(client, table, f"daily#{day}", daily_cap, epoch + DAILY_TTL_SECONDS):
        raise LimitReached(DAILY_LIMIT_MESSAGE, "daily")
