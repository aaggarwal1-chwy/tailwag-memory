from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


@dataclass(frozen=True)
class IdempotencyStart:
    """Result of attempting to claim a job id."""

    started: bool
    status: str | None = None


class DynamoDBJobIdempotencyStore:
    """Track worker job attempts in a DynamoDB-style table."""

    def __init__(self, table: Any, *, ttl_seconds: int = 7 * 24 * 60 * 60) -> None:
        """Create an idempotency store from a boto3 DynamoDB Table-like object."""
        self.table = table
        self.ttl_seconds = ttl_seconds

    def start_job(self, job_id: str, *, job_type: str) -> IdempotencyStart:
        """Claim one job id unless it has already been claimed."""
        now = _epoch_seconds()
        item = {
            "job_id": job_id,
            "job_type": job_type,
            "status": "running",
            "attempt_count": 1,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(job_id)",
            )
        except Exception as exc:
            if not _is_conditional_check_failed(exc):
                raise
            existing = self.table.get_item(Key={"job_id": job_id}).get("Item", {})
            return IdempotencyStart(started=False, status=existing.get("status"))
        return IdempotencyStart(started=True, status="running")

    def mark_succeeded(self, job_id: str, *, result: dict[str, Any] | None = None) -> None:
        """Mark a claimed job as succeeded."""
        names = {"#status": "status"}
        values: dict[str, Any] = {
            ":status": "succeeded",
            ":updated_at": _epoch_seconds(),
        }
        expression = "SET #status = :status, updated_at = :updated_at"
        if result is not None:
            values[":result"] = result
            expression += ", result = :result"
        self.table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def mark_failed(self, job_id: str, *, error: str) -> None:
        """Mark a claimed job as failed."""
        self.table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at, error = :error",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "failed",
                ":updated_at": _epoch_seconds(),
                ":error": error,
            },
        )


class InMemoryJobIdempotencyStore:
    """Small idempotency store for tests and local handler injection."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def start_job(self, job_id: str, *, job_type: str) -> IdempotencyStart:
        if job_id in self.items:
            return IdempotencyStart(started=False, status=self.items[job_id].get("status"))
        self.items[job_id] = {"job_id": job_id, "job_type": job_type, "status": "running"}
        return IdempotencyStart(started=True, status="running")

    def mark_succeeded(self, job_id: str, *, result: dict[str, Any] | None = None) -> None:
        self.items.setdefault(job_id, {"job_id": job_id})
        self.items[job_id].update({"status": "succeeded", "result": result or {}})

    def mark_failed(self, job_id: str, *, error: str) -> None:
        self.items.setdefault(job_id, {"job_id": job_id})
        self.items[job_id].update({"status": "failed", "error": error})


def _epoch_seconds() -> int:
    return int(time())


def _is_conditional_check_failed(exc: Exception) -> bool:
    if exc.__class__.__name__ == "ConditionalCheckFailedException":
        return True
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"
