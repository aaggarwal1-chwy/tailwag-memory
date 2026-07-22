from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class IdempotencyStart:
    """Result of attempting to claim a job id."""

    started: bool
    status: str | None = None
    claim_token: str | None = None


class IdempotencyClaimLost(RuntimeError):
    """Raised when a worker finishes after its job lease was reclaimed."""


class DynamoDBJobIdempotencyStore:
    """Track retry-safe worker job claims in a DynamoDB-style table."""

    def __init__(
        self,
        table: Any,
        *,
        ttl_seconds: int = 7 * 24 * 60 * 60,
        lease_seconds: int = 15 * 60,
        clock: Callable[[], int] | None = None,
    ) -> None:
        """Create an idempotency store from a boto3 DynamoDB Table-like object."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.table = table
        self.ttl_seconds = ttl_seconds
        self.lease_seconds = lease_seconds
        self.clock = clock or _epoch_seconds

    def start_job(self, job_id: str, *, job_type: str) -> IdempotencyStart:
        """Atomically claim a new, failed, or expired-running job."""
        now = self.clock()
        claim_token = uuid4().hex
        try:
            self.table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=(
                    "SET job_type = :job_type, #status = :running, "
                    "created_at = if_not_exists(created_at, :now), updated_at = :now, "
                    "lease_expires_at = :lease_expires_at, claim_token = :claim_token, expires_at = :expires_at "
                    "REMOVE #error, #result ADD attempt_count :attempt_increment"
                ),
                ConditionExpression=(
                    "attribute_not_exists(job_id) OR #status = :failed OR "
                    "(#status = :running AND "
                    "(attribute_not_exists(lease_expires_at) OR lease_expires_at <= :now))"
                ),
                ExpressionAttributeNames={"#status": "status", "#error": "error", "#result": "result"},
                ExpressionAttributeValues={
                    ":running": "running",
                    ":failed": "failed",
                    ":job_type": job_type,
                    ":now": now,
                    ":lease_expires_at": now + self.lease_seconds,
                    ":claim_token": claim_token,
                    ":expires_at": now + self.ttl_seconds,
                    ":attempt_increment": 1,
                },
            )
        except Exception as exc:
            if not _is_conditional_check_failed(exc):
                raise
            existing = self.table.get_item(Key={"job_id": job_id}).get("Item", {})
            return IdempotencyStart(started=False, status=existing.get("status"))
        return IdempotencyStart(started=True, status="running", claim_token=claim_token)

    def mark_succeeded(
        self,
        job_id: str,
        *,
        claim_token: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job succeeded only while its current lease is held."""
        names = {"#status": "status"}
        values: dict[str, Any] = {
            ":status": "succeeded",
            ":running": "running",
            ":claim_token": claim_token,
            ":updated_at": self.clock(),
        }
        expression = "SET #status = :status, updated_at = :updated_at"
        if result is not None:
            names["#result"] = "result"
            values[":result"] = result
            expression += ", #result = :result"
        self._mark(job_id, claim_token, expression, names, values)

    def mark_failed(self, job_id: str, *, claim_token: str, error: str) -> None:
        """Mark a job failed only while its current lease is held."""
        self._mark(
            job_id,
            claim_token,
            "SET #status = :status, updated_at = :updated_at, #error = :error",
            {"#status": "status", "#error": "error"},
            {
                ":status": "failed",
                ":running": "running",
                ":claim_token": claim_token,
                ":updated_at": self.clock(),
                ":error": error,
            },
        )

    def _mark(
        self,
        job_id: str,
        claim_token: str,
        expression: str,
        names: dict[str, str],
        values: dict[str, Any],
    ) -> None:
        try:
            self.table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=expression,
                ConditionExpression="#status = :running AND claim_token = :claim_token",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as exc:
            if _is_conditional_check_failed(exc):
                raise IdempotencyClaimLost(job_id) from exc
            raise


class InMemoryJobIdempotencyStore:
    """Small retry-safe idempotency store for tests and local injection."""

    def __init__(self, *, lease_seconds: int = 15 * 60, clock: Callable[[], int] | None = None) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.items: dict[str, dict[str, Any]] = {}
        self.lease_seconds = lease_seconds
        self.clock = clock or _epoch_seconds

    def start_job(self, job_id: str, *, job_type: str) -> IdempotencyStart:
        now = self.clock()
        item = self.items.get(job_id)
        if item is not None:
            reclaimable = item.get("status") == "failed" or (
                item.get("status") == "running" and item.get("lease_expires_at", 0) <= now
            )
            if not reclaimable:
                return IdempotencyStart(started=False, status=item.get("status"))
            attempt_count = int(item.get("attempt_count", 0)) + 1
        else:
            item = {"job_id": job_id, "created_at": now}
            self.items[job_id] = item
            attempt_count = 1
        claim_token = uuid4().hex
        item.update(
            {
                "job_type": job_type,
                "status": "running",
                "attempt_count": attempt_count,
                "updated_at": now,
                "lease_expires_at": now + self.lease_seconds,
                "claim_token": claim_token,
            }
        )
        item.pop("error", None)
        item.pop("result", None)
        return IdempotencyStart(started=True, status="running", claim_token=claim_token)

    def mark_succeeded(self, job_id: str, *, claim_token: str, result: dict[str, Any] | None = None) -> None:
        item = self._claimed_item(job_id, claim_token)
        item.update({"status": "succeeded", "updated_at": self.clock(), "result": result or {}})

    def mark_failed(self, job_id: str, *, claim_token: str, error: str) -> None:
        item = self._claimed_item(job_id, claim_token)
        item.update({"status": "failed", "updated_at": self.clock(), "error": error})

    def _claimed_item(self, job_id: str, claim_token: str) -> dict[str, Any]:
        item = self.items.get(job_id)
        if item is None or item.get("status") != "running" or item.get("claim_token") != claim_token:
            raise IdempotencyClaimLost(job_id)
        return item


def _epoch_seconds() -> int:
    return int(time())


def _is_conditional_check_failed(exc: Exception) -> bool:
    if exc.__class__.__name__ == "ConditionalCheckFailedException":
        return True
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"
