"""Map Neo4j relay query rows to package models."""

from __future__ import annotations

from .models import RelayMessageEnvelope, RelayMessageStatus, RelayTransitionResult


def status(row: dict[str, object]) -> RelayMessageStatus:
    return RelayMessageStatus(
        **{
            field: str(row.get(field) or "")
            for field in RelayMessageStatus.__dataclass_fields__
        }
    )


def envelope(row: dict[str, object]) -> RelayMessageEnvelope:
    return RelayMessageEnvelope(
        **{
            field: str(row.get(field) or "")
            for field in RelayMessageEnvelope.__dataclass_fields__
        }
    )


def transition_or_conflict(
    message_id: str,
    rows: list[dict[str, object]],
    *,
    claim_token: str = "",
    reason: str = "",
) -> RelayTransitionResult:
    if not rows:
        return RelayTransitionResult(
            message_id=message_id,
            status="conflict",
            reason="message state, recipient, robot, or claim token did not match",
        )
    row = rows[0]
    return RelayTransitionResult(
        message_id=str(row.get("message_id") or message_id),
        status=str(row.get("status") or ""),
        claim_token=claim_token,
        body=str(row["body"]) if row.get("body") is not None else None,
        reason=reason,
    )


def count(rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    value = rows[0].get("count", 0)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
