"""Neo4j-backed, permission-gated robot message relay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable
from uuid import uuid4

from .config import Settings
from .db import QueryRunner
from .models import (
    RelayMessageEnvelope,
    RelayMessageInput,
    RelayMessageStatus,
    RelayPolicyResult,
    RelayTransitionResult,
)
from .relay_message_identity import resolve_identities
from .relay_message_rows import envelope as _envelope, status as _status
from .relay_message_transitions import RelayMessageTransitions
from .relay_message_validation import (
    default_settings as _default_settings,
    email as _email,
    parse_timestamp as _parse_timestamp,
    required as _required,
    utc_datetime,
    validate_input,
)
from .relay_policy import OpenAIRelaySafetyProvider, RelaySafetyProvider


class RelayPolicyRejectedError(ValueError):
    """The exact proposed body failed the workplace relay policy."""


class RelayRateLimitError(ValueError):
    """The sender or sender-recipient active-message limit was reached."""


@dataclass(frozen=True)
class RelayMaintenanceResult:
    """Counts produced by one idempotent maintenance pass."""

    expired_count: int = 0
    claims_released_count: int = 0
    uncertain_count: int = 0


class RelayMessageService:
    """Enforce relay identity, policy, lifecycle, and content-release rules."""

    def __init__(
        self,
        runner: QueryRunner,
        *,
        settings: Settings | None = None,
        safety_provider: RelaySafetyProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.runner = runner
        self.settings = settings or getattr(runner, "settings", None) or _default_settings()
        self.safety_provider = safety_provider or OpenAIRelaySafetyProvider(
            api_key=self.settings.openai_api_key,
            model=self.settings.relay_policy_model,
            timeout_seconds=self.settings.relay_policy_timeout_seconds,
            max_retries=self.settings.relay_policy_max_retries,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._transitions = RelayMessageTransitions(runner, clock=self._now)

    def check_policy(self, message: RelayMessageInput, *, robot_id: str) -> RelayPolicyResult:
        """Resolve both people and screen the exact proposed message without storing it."""
        normalized = self._validate_input(message, robot_id=robot_id)
        return self._check_normalized_policy(normalized, robot_id=robot_id)

    def _check_normalized_policy(
        self,
        message: RelayMessageInput,
        *,
        robot_id: str,
    ) -> RelayPolicyResult:
        identities = resolve_identities(
            self.runner,
            sender_email=message.sender_email,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        if identities is None:
            return RelayPolicyResult(
                allowed=False,
                reason="Sender, recipient, or assigned robot could not be resolved uniquely.",
                sender_email=message.sender_email,
                recipient_email=message.recipient_email,
            )
        decision = self.safety_provider.screen(body=message.body)
        return RelayPolicyResult(
            allowed=decision.allowed,
            reason=decision.reason,
            **identities,
        )

    def create_confirmed(self, message: RelayMessageInput, *, robot_id: str) -> RelayMessageStatus:
        """Persist only an already-confirmed message after repeating all server checks."""
        normalized = self._validate_input(message, robot_id=robot_id)
        policy = self._check_normalized_policy(normalized, robot_id=robot_id)
        if not policy.allowed:
            raise RelayPolicyRejectedError(
                policy.reason or "relay message was rejected by policy"
            )
        now = self._now()
        lock_token = str(uuid4())
        rows = self.runner.run(
            """
            MATCH (robot:Robot {id: $robot_id})
            MATCH (sender:Person {id: $sender_person_id})
            MATCH (recipient:Person {id: $recipient_person_id})
            SET sender._relay_create_lock = $lock_token
            WITH robot, sender, recipient
            OPTIONAL MATCH (sender)-[:SENT_RELAY]->(pending:RelayMessage)-[:FOR_RECIPIENT]->(recipient)
            WHERE pending.status IN ['pending', 'claimed', 'permission_granted', 'delivering']
              AND pending.expires_at > $now
            WITH robot, sender, recipient, count(DISTINCT pending) AS pair_pending
            OPTIONAL MATCH (sender)-[:SENT_RELAY]->(today:RelayMessage)
            WHERE today.created_at >= $day_start
            WITH robot, sender, recipient, pair_pending, count(DISTINCT today) AS daily_sent
            WITH robot, sender, recipient,
                 pair_pending < $max_pending_per_pair
                   AND daily_sent < $max_sends_per_day AS within_limits
            FOREACH (_ IN CASE WHEN within_limits THEN [1] ELSE [] END |
              CREATE (created:RelayMessage {
                id: $message_id,
                body: $body,
                metadata_json: $metadata_json,
                status: 'pending',
                sender_email_snapshot: $sender_email,
                recipient_email_snapshot: $recipient_email,
                sender_display_name_snapshot: $sender_display_name,
                recipient_display_name_snapshot: $recipient_display_name,
                assigned_robot_id: $robot_id,
                created_at: $now,
                updated_at: $now,
                deliver_after: $deliver_after,
                expires_at: $expires_at,
                attempt_count: 0,
                _relay_create_token: $lock_token
              })
              CREATE (sender)-[:SENT_RELAY]->(created)
              CREATE (created)-[:FOR_RECIPIENT]->(recipient)
              CREATE (created)-[:ASSIGNED_TO]->(robot)
            )
            OPTIONAL MATCH (message:RelayMessage {id: $message_id})
            WHERE message._relay_create_token = $lock_token
            WITH sender, recipient, message, within_limits
            REMOVE sender._relay_create_lock, message._relay_create_token
            WITH sender, recipient, message, within_limits
            WHERE within_limits AND message IS NOT NULL
            RETURN message.id AS message_id,
                   sender.id AS sender_person_id,
                   recipient.id AS recipient_person_id,
                   message.sender_email_snapshot AS sender_email,
                   message.recipient_email_snapshot AS recipient_email,
                   message.sender_display_name_snapshot AS sender_display_name,
                   message.recipient_display_name_snapshot AS recipient_display_name,
                   message.assigned_robot_id AS assigned_robot_id,
                   message.status AS status,
                   message.created_at AS created_at,
                   message.deliver_after AS deliver_after,
                   message.expires_at AS expires_at,
                   message.updated_at AS updated_at,
                   coalesce(message.last_failure_reason, '') AS last_failure_reason,
                   coalesce(message.failed_at, '') AS last_failure_at
            """,
            {
                "message_id": normalized.id,
                "lock_token": lock_token,
                "body": normalized.body,
                "metadata_json": json.dumps(normalized.metadata, sort_keys=True, separators=(",", ":")),
                "sender_person_id": policy.sender_person_id,
                "recipient_person_id": policy.recipient_person_id,
                "sender_email": policy.sender_email,
                "recipient_email": policy.recipient_email,
                "sender_display_name": policy.sender_display_name,
                "recipient_display_name": policy.recipient_display_name,
                "robot_id": _required(robot_id, "robot_id"),
                "now": now.isoformat(),
                "day_start": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "deliver_after": normalized.deliver_after,
                "expires_at": normalized.expires_at,
                "max_pending_per_pair": self.settings.relay_max_pending_per_pair,
                "max_sends_per_day": self.settings.relay_max_sends_per_sender_per_day,
            },
        )
        if not rows:
            raise RelayRateLimitError(
                "relay rate limit reached or message id already exists"
            )
        return _status(rows[0])

    def claim_next_envelope(
        self,
        *,
        recipient_email: str,
        robot_id: str,
    ) -> RelayMessageEnvelope | None:
        """Atomically reserve one due message while withholding its body."""
        now = self._now().isoformat()
        rows = self.runner.run(
            """
            MATCH (robot:Robot {id: $robot_id})
            SET robot._relay_claim_lock = randomUUID()
            WITH robot
            OPTIONAL MATCH (message:RelayMessage)-[:ASSIGNED_TO]->(robot)
            USING INDEX message:RelayMessage(
              assigned_robot_id, status, deliver_after, created_at
            )
            WHERE message.assigned_robot_id = $robot_id
              AND message.status = 'pending'
              AND message.deliver_after <= $now
              AND message.created_at IS NOT NULL
              AND message.expires_at > $now
            OPTIONAL MATCH (message)-[:FOR_RECIPIENT]->(recipient:Person)
            OPTIONAL MATCH (sender:Person)-[:SENT_RELAY]->(message)
            WITH robot,
                 collect(
                   CASE
                     WHEN message IS NOT NULL
                       AND toLower(trim(recipient.email)) = $recipient_email
                       AND coalesce(recipient.status, 'active') <> 'archived'
                       AND coalesce(sender.status, 'active') <> 'archived'
                     THEN {
                       message: message,
                       sender: sender,
                       recipient: recipient
                     }
                   END
                 ) AS eligible_candidates
            UNWIND CASE
              WHEN size(eligible_candidates) = 0
                THEN [{message: null, sender: null, recipient: null}]
              ELSE eligible_candidates
            END AS eligible
            WITH robot,
                 eligible.message AS message,
                 eligible.sender AS sender,
                 eligible.recipient AS recipient
            ORDER BY elementId(message)
            SET message._relay_write_lock = randomUUID()
            WITH robot, collect({
              message: message,
              sender: sender,
              recipient: recipient
            }) AS candidates
            UNWIND candidates AS candidate
            WITH robot, candidates, candidate,
                 candidate.message IS NOT NULL
                   AND candidate.message.status = 'pending'
                   AND candidate.message.deliver_after <= $now
                   AND candidate.message.expires_at > $now
                   AND toLower(trim(candidate.recipient.email)) = $recipient_email
                   AND coalesce(candidate.recipient.status, 'active') <> 'archived'
                   AND coalesce(candidate.sender.status, 'active') <> 'archived'
                   AS can_claim
            ORDER BY can_claim DESC,
                     candidate.message.created_at,
                     candidate.message.id
            WITH robot, candidates,
                 head(collect({candidate: candidate, can_claim: can_claim})) AS selected
            WITH robot, candidates,
                 selected.candidate.message AS message,
                 selected.candidate.sender AS sender,
                 selected.candidate.recipient AS recipient,
                 selected.can_claim AS can_claim
            FOREACH (_ IN CASE WHEN can_claim THEN [1] ELSE [] END |
              SET message.status = 'claimed',
                  message.claim_token = randomUUID(),
                  message.claimed_at = $now,
                  message.updated_at = $now
            )
            UNWIND candidates AS candidate
            WITH robot, message, sender, recipient, can_claim,
                 candidate.message AS locked_message
            REMOVE locked_message._relay_write_lock
            WITH DISTINCT robot, message, sender, recipient, can_claim
            REMOVE robot._relay_claim_lock
            WITH message, sender, recipient, can_claim
            WHERE can_claim
            RETURN message.id AS message_id,
                   sender.id AS sender_person_id,
                   recipient.id AS recipient_person_id,
                   message.sender_email_snapshot AS sender_email,
                   message.recipient_email_snapshot AS recipient_email,
                   message.sender_display_name_snapshot AS sender_display_name,
                   message.recipient_display_name_snapshot AS recipient_display_name,
                   message.assigned_robot_id AS assigned_robot_id,
                   message.created_at AS created_at,
                   message.deliver_after AS deliver_after,
                   message.expires_at AS expires_at,
                   message.status AS status,
                   message.claim_token AS claim_token
            """,
            {
                "recipient_email": _email(recipient_email),
                "robot_id": _required(robot_id, "robot_id"),
                "now": now,
            },
        )
        return _envelope(rows[0]) if rows else None

    def grant_permission(
        self,
        message_id: str,
        *,
        claim_token: str,
        recipient_email: str,
        robot_id: str,
    ) -> RelayTransitionResult:
        """Release the exact body only after the intended recipient grants permission."""
        return self._transitions.recipient_transition(
            message_id,
            claim_token=claim_token,
            recipient_email=recipient_email,
            robot_id=robot_id,
            status_from="claimed",
            status_to="permission_granted",
            timestamp_property="permission_granted_at",
            include_body=True,
        )

    def decline(
        self,
        message_id: str,
        *,
        claim_token: str,
        recipient_email: str,
        robot_id: str,
    ) -> RelayTransitionResult:
        """Record a terminal decline without exposing content."""
        return self._transitions.recipient_transition(
            message_id,
            claim_token=claim_token,
            recipient_email=recipient_email,
            robot_id=robot_id,
            status_from="claimed",
            status_to="declined",
            timestamp_property="declined_at",
        )

    def snooze(
        self,
        message_id: str,
        *,
        claim_token: str,
        recipient_email: str,
        robot_id: str,
        deliver_after: str,
    ) -> RelayTransitionResult:
        """Return a claimed message to pending for a recipient-selected later time."""
        return self._transitions.snooze(
            message_id,
            claim_token=claim_token,
            recipient_email=recipient_email,
            robot_id=robot_id,
            deliver_after=deliver_after,
        )

    def begin_delivery(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
    ) -> RelayTransitionResult:
        """Move a permission-granted message to delivering immediately before TTS."""
        return self._transitions.machine_transition(
            message_id,
            claim_token=claim_token,
            robot_id=robot_id,
            status_from="permission_granted",
            status_to="delivering",
            timestamp_property="delivery_started_at",
        )

    def complete_delivery(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
    ) -> RelayTransitionResult:
        """Mark delivery complete only after natural audio playback completion."""
        return self._transitions.machine_transition(
            message_id,
            claim_token=claim_token,
            robot_id=robot_id,
            status_from="delivering",
            status_to="delivered",
            timestamp_property="delivered_at",
        )

    def record_playback_failure(
        self,
        message_id: str,
        *,
        claim_token: str,
        robot_id: str,
        reason: str,
        audio_started: bool,
    ) -> RelayTransitionResult:
        """Avoid automatic replay whenever audio may already have been heard."""
        return self._transitions.record_playback_failure(
            message_id,
            claim_token=claim_token,
            robot_id=robot_id,
            reason=reason,
            audio_started=audio_started,
        )

    def list_sender_statuses(
        self,
        *,
        sender_email: str,
        robot_id: str,
        limit: int = 50,
    ) -> list[RelayMessageStatus]:
        """Return statuses, including failure detail in status, but never message bodies."""
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        rows = self.runner.run(
            """
            MATCH (sender:Person)-[:SENT_RELAY]->(message:RelayMessage)
            MATCH (message)-[:FOR_RECIPIENT]->(recipient:Person)
            WHERE toLower(trim(sender.email)) = $sender_email
              AND message.assigned_robot_id = $robot_id
              AND coalesce(sender.status, 'active') <> 'archived'
            RETURN message.id AS message_id,
                   sender.id AS sender_person_id,
                   recipient.id AS recipient_person_id,
                   message.sender_email_snapshot AS sender_email,
                   message.recipient_email_snapshot AS recipient_email,
                   message.sender_display_name_snapshot AS sender_display_name,
                   message.recipient_display_name_snapshot AS recipient_display_name,
                   message.assigned_robot_id AS assigned_robot_id,
                   message.status AS status,
                   message.created_at AS created_at,
                   message.deliver_after AS deliver_after,
                   message.expires_at AS expires_at,
                   message.updated_at AS updated_at,
                   coalesce(message.last_failure_reason, '') AS last_failure_reason,
                   coalesce(message.failed_at, '') AS last_failure_at
            ORDER BY message.created_at DESC
            LIMIT $limit
            """,
            {
                "sender_email": _email(sender_email),
                "robot_id": _required(robot_id, "robot_id"),
                "limit": limit,
            },
        )
        return [_status(row) for row in rows]

    def run_maintenance(
        self,
        *,
        now: str = "",
        claim_timeout_seconds: int = 120,
    ) -> RelayMaintenanceResult:
        """Expire messages and recover abandoned claims without risking duplicate speech."""
        if claim_timeout_seconds <= 0:
            raise ValueError("claim_timeout_seconds must be positive")
        current = _parse_timestamp(now, "now") if now else self._now()
        counts = self._transitions.run_maintenance(
            now=current,
            claim_timeout_seconds=claim_timeout_seconds,
        )
        return RelayMaintenanceResult(
            expired_count=counts.expired,
            claims_released_count=counts.claims_released,
            uncertain_count=counts.uncertain,
        )

    def _validate_input(self, message: RelayMessageInput, *, robot_id: str) -> RelayMessageInput:
        return validate_input(
            message,
            robot_id=robot_id,
            settings=self.settings,
            now=self._now(),
        )

    def _now(self) -> datetime:
        return utc_datetime(self.clock())
