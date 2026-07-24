"""Map Neo4j relay query rows to package models."""

from __future__ import annotations

from .models import RelayMessageEnvelope, RelayMessageStatus, RelayTransitionResult

_STATUS_FIELDS = tuple(RelayMessageStatus.__dataclass_fields__)
_ENVELOPE_FIELDS = tuple(RelayMessageEnvelope.__dataclass_fields__)


def status(row: dict[str, object]) -> RelayMessageStatus:
    return RelayMessageStatus(
        **{field: str(row.get(field) or "") for field in _STATUS_FIELDS}
    )


def envelope(row: dict[str, object]) -> RelayMessageEnvelope:
    return RelayMessageEnvelope(
        **{field: str(row.get(field) or "") for field in _ENVELOPE_FIELDS}
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
