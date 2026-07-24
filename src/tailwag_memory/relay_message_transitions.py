"""Lifecycle transitions for Neo4j-backed relay messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from .db import QueryRunner
from .models import RelayTransitionResult
from .relay_message_rows import transition_or_conflict
from .relay_message_validation import email, parse_timestamp, required


@dataclass(frozen=True)
class RelayMaintenanceCounts:
    expired: int = 0
    claims_released: int = 0
    uncertain: int = 0


class RelayMessageTransitions:
    """Execute compare-and-set transitions without owning service policy."""

    def __init__(
        self,
        runner: QueryRunner,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.runner = runner
        self.clock = clock

    def snooze(
        self,
        message_id: str,
        *,
        claim_token: str,
        recipient_email: str,
        robot_id: str,
        deliver_after: str,
    ) -> RelayTransitionResult:
        deferred = parse_timestamp(deliver_after, "deliver_after")
        now = self.clock()
        if deferred <= now:
            raise ValueError("deliver_after must be in the future")
        rows = self.runner.run(
            """
            MATCH (message:RelayMessage {id: $message_id})
            SET message._relay_write_lock = randomUUID()
            WITH message
            OPTIONAL MATCH (message)-[:FOR_RECIPIENT]->(recipient:Person)
            WITH message, recipient,
                 message.assigned_robot_id = $robot_id
                   AND message.status = 'claimed'
                   AND message.claim_token = $claim_token
                   AND toLower(trim(recipient.email)) = $recipient_email
                   AND coalesce(recipient.status, 'active') <> 'archived'
                   AND message.expires_at > $deliver_after AS can_transition
            FOREACH (_ IN CASE WHEN can_transition THEN [1] ELSE [] END |
              SET message.status = 'pending',
                  message.deliver_after = $deliver_after,
                  message.updated_at = $now
              REMOVE message.claim_token, message.claimed_at
            )
            WITH message, can_transition
            REMOVE message._relay_write_lock
            WITH message, can_transition
            WHERE can_transition
            RETURN message.id AS message_id, message.status AS status
            """,
            {
                "message_id": required(message_id, "message_id"),
                "claim_token": required(claim_token, "claim_token"),
                "recipient_email": email(recipient_email),
                "robot_id": required(robot_id, "robot_id"),
                "deliver_after": deferred.isoformat(),
                "now": now.isoformat(),
            },
        )
        return transition_or_conflict(message_id, rows)

    def release_before_playback(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
    ) -> RelayTransitionResult:
        """Release a matching claim while playback is still impossible."""
        now = self.clock().isoformat()
        rows = self.runner.run(
            """
            MATCH (message:RelayMessage {id: $message_id})
            SET message._relay_write_lock = randomUUID()
            WITH message,
                 message.assigned_robot_id = $robot_id
                   AND message.status IN ['claimed', 'permission_granted']
                   AND message.claim_token = $claim_token AS can_transition
            FOREACH (_ IN CASE WHEN can_transition THEN [1] ELSE [] END |
              SET message.status = 'pending',
                  message.deliver_after = $now,
                  message.updated_at = $now
              REMOVE message.claim_token, message.claimed_at,
                     message.permission_granted_at, message.delivery_started_at
            )
            WITH message, can_transition
            REMOVE message._relay_write_lock
            WITH message, can_transition
            WHERE can_transition
            RETURN message.id AS message_id, message.status AS status
            """,
            {
                "message_id": required(message_id, "message_id"),
                "claim_token": required(claim_token, "claim_token"),
                "robot_id": required(robot_id, "robot_id"),
                "now": now,
            },
        )
        return transition_or_conflict(message_id, rows)

    def record_playback_failure(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
        reason: str,
        audio_started: bool,
    ) -> RelayTransitionResult:
        now = self.clock().isoformat()
        status = "delivery_uncertain" if audio_started else "pending"
        rows = self.runner.run(
            """
            MATCH (message:RelayMessage {id: $message_id})
            SET message._relay_write_lock = randomUUID()
            WITH message,
                 message.assigned_robot_id = $robot_id
                   AND message.claim_token = $claim_token
                   AND (
                     ($audio_started AND message.status = 'delivering')
                     OR (
                       NOT $audio_started
                       AND message.status IN ['permission_granted', 'delivering']
                     )
                   ) AS can_transition
            FOREACH (_ IN CASE WHEN can_transition THEN [1] ELSE [] END |
              SET message.status = $status,
                  message.failed_at = $now,
                  message.last_failure_reason = $reason,
                  message.last_failure_audio_started = $audio_started,
                  message.updated_at = $now
            )
            FOREACH (_ IN CASE WHEN can_transition AND NOT $audio_started THEN [1] ELSE [] END |
                SET message.deliver_after = $now
                REMOVE message.claim_token, message.claimed_at,
                       message.permission_granted_at, message.delivery_started_at
            )
            WITH message, can_transition
            REMOVE message._relay_write_lock
            WITH message, can_transition
            WHERE can_transition
            RETURN message.id AS message_id, message.status AS status
            """,
            {
                "message_id": required(message_id, "message_id"),
                "claim_token": required(claim_token, "claim_token"),
                "robot_id": required(robot_id, "robot_id"),
                "reason": required(reason, "reason")[:500],
                "audio_started": bool(audio_started),
                "status": status,
                "now": now,
            },
        )
        return transition_or_conflict(message_id, rows, reason=reason)

    def run_maintenance(
        self,
        *,
        now: datetime,
        claim_timeout_seconds: int,
    ) -> RelayMaintenanceCounts:
        stale_before = (now - timedelta(seconds=claim_timeout_seconds)).isoformat()
        rows = self.runner.run(
            """
            MATCH (message:RelayMessage)
            USING INDEX message:RelayMessage(status)
            WHERE message.status IN ['pending', 'claimed', 'permission_granted', 'delivering']
              AND (
                (
                  message.status IN ['pending', 'claimed', 'permission_granted']
                  AND message.expires_at <= $now
                )
                OR (
                  message.status IN ['claimed', 'permission_granted']
                  AND message.claimed_at < $stale_before
                  AND message.expires_at > $now
                )
                OR (
                  message.status = 'delivering'
                  AND message.delivery_started_at < $stale_before
                )
              )
            WITH message ORDER BY elementId(message)
            SET message._relay_write_lock = randomUUID()
            WITH message,
                 CASE
                   WHEN message.status IN ['pending', 'claimed', 'permission_granted']
                     AND message.expires_at <= $now
                     THEN 'expire'
                   WHEN message.status IN ['claimed', 'permission_granted']
                     AND message.claimed_at < $stale_before
                     AND message.expires_at > $now
                     THEN 'release'
                   WHEN message.status = 'delivering'
                     AND message.delivery_started_at < $stale_before
                     THEN 'uncertain'
                   ELSE ''
                 END AS maintenance_action
            FOREACH (_ IN CASE WHEN maintenance_action = 'expire' THEN [1] ELSE [] END |
              SET message.status = 'expired', message.updated_at = $now
              REMOVE message.claim_token, message.claimed_at,
                     message.permission_granted_at
            )
            FOREACH (_ IN CASE WHEN maintenance_action = 'release' THEN [1] ELSE [] END |
              SET message.status = 'pending',
                  message.deliver_after = $now,
                  message.updated_at = $now
              REMOVE message.claim_token, message.claimed_at,
                     message.permission_granted_at
            )
            FOREACH (_ IN CASE WHEN maintenance_action = 'uncertain' THEN [1] ELSE [] END |
              SET message.status = 'delivery_uncertain',
                  message.failed_at = $now,
                  message.last_failure_reason = 'delivery worker timed out after audio start',
                  message.last_failure_audio_started = true,
                  message.updated_at = $now
            )
            WITH message, maintenance_action
            REMOVE message._relay_write_lock
            RETURN sum(CASE WHEN maintenance_action = 'expire' THEN 1 ELSE 0 END)
                     AS expired_count,
                   sum(CASE WHEN maintenance_action = 'release' THEN 1 ELSE 0 END)
                     AS claims_released_count,
                   sum(CASE WHEN maintenance_action = 'uncertain' THEN 1 ELSE 0 END)
                     AS uncertain_count
            """,
            {"now": now.isoformat(), "stale_before": stale_before},
        )
        row = rows[0] if rows else {}
        return RelayMaintenanceCounts(
            expired=_integer_count(row.get("expired_count")),
            claims_released=_integer_count(row.get("claims_released_count")),
            uncertain=_integer_count(row.get("uncertain_count")),
        )

    def recipient_transition(
        self,
        message_id: str,
        *,
        claim_token: str,
        recipient_email: str,
        robot_id: str,
        status_from: str,
        status_to: str,
        timestamp_property: str,
        include_body: bool = False,
    ) -> RelayTransitionResult:
        now = self.clock().isoformat()
        rows = self.runner.run(
            f"""
            MATCH (message:RelayMessage {{id: $message_id}})
            SET message._relay_write_lock = randomUUID()
            WITH message
            OPTIONAL MATCH (sender:Person)-[:SENT_RELAY]->(message)
            OPTIONAL MATCH (message)-[:FOR_RECIPIENT]->(recipient:Person)
            WITH message, sender, recipient,
                 message.assigned_robot_id = $robot_id
                   AND message.status = $status_from
                   AND message.claim_token = $claim_token
                   AND message.expires_at > $now
                   AND toLower(trim(recipient.email)) = $recipient_email
                   AND coalesce(recipient.status, 'active') <> 'archived'
                   AND coalesce(sender.status, 'active') <> 'archived' AS can_transition
            FOREACH (_ IN CASE WHEN can_transition THEN [1] ELSE [] END |
              SET message.status = $status_to,
                  message.{timestamp_property} = $now,
                  message.updated_at = $now
            )
            WITH message, can_transition
            REMOVE message._relay_write_lock
            WITH message, can_transition
            WHERE can_transition
            RETURN message.id AS message_id,
                   message.status AS status
                   {", message.body AS body" if include_body else ""}
            """,
            {
                "message_id": required(message_id, "message_id"),
                "claim_token": required(claim_token, "claim_token"),
                "recipient_email": email(recipient_email),
                "robot_id": required(robot_id, "robot_id"),
                "status_from": status_from,
                "status_to": status_to,
                "now": now,
            },
        )
        return transition_or_conflict(message_id, rows, claim_token=claim_token)

    def machine_transition(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
        status_from: str,
        status_to: str,
        timestamp_property: str,
    ) -> RelayTransitionResult:
        now = self.clock().isoformat()
        rows = self.runner.run(
            f"""
            MATCH (message:RelayMessage {{id: $message_id}})
            SET message._relay_write_lock = randomUUID()
            WITH message
            OPTIONAL MATCH (sender:Person)-[:SENT_RELAY]->(message)
            WITH message, sender,
                 message.assigned_robot_id = $robot_id
                   AND message.status = $status_from
                   AND message.claim_token = $claim_token
                   AND message.expires_at > $now
                   AND coalesce(sender.status, 'active') <> 'archived' AS can_transition
            FOREACH (_ IN CASE WHEN can_transition THEN [1] ELSE [] END |
              SET message.status = $status_to,
                  message.{timestamp_property} = $now,
                  message.updated_at = $now,
                  message.attempt_count = coalesce(message.attempt_count, 0) +
                    CASE WHEN $status_to = 'delivering' THEN 1 ELSE 0 END
            )
            WITH message, can_transition
            REMOVE message._relay_write_lock
            WITH message, can_transition
            WHERE can_transition
            RETURN message.id AS message_id, message.status AS status
            """,
            {
                "message_id": required(message_id, "message_id"),
                "claim_token": required(claim_token, "claim_token"),
                "robot_id": required(robot_id, "robot_id"),
                "status_from": status_from,
                "status_to": status_to,
                "now": now,
            },
        )
        return transition_or_conflict(message_id, rows, claim_token=claim_token)


def _integer_count(value: object) -> int:
    """Return a Neo4j aggregate count without accepting booleans or strings."""
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
