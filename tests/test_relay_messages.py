from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tailwag_memory.models import RelayMessageInput
from tailwag_memory.relay_message_validation import validate_input
from tailwag_memory.relay_messages import RelayMessageService
from tailwag_memory.relay_policy import RelaySafetyDecision
from tests.helpers import RecordingQueryRunner, test_settings


NOW = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)


class _Safety:
    def __init__(self, *, allowed: bool = True, reason: str = "") -> None:
        self.decision = RelaySafetyDecision(allowed=allowed, reason=reason)
        self.bodies: list[str] = []

    def screen(self, *, body: str) -> RelaySafetyDecision:
        self.bodies.append(body)
        return self.decision


def _identity_row() -> dict[str, str]:
    return {
        "sender_person_id": "person-alice",
        "recipient_person_id": "person-bob",
        "sender_email": "alice@example.com",
        "recipient_email": "bob@example.com",
        "sender_display_name": "Alice",
        "recipient_display_name": "Bob",
    }


def _message(**overrides: object) -> RelayMessageInput:
    values: dict[str, object] = {
        "id": "relay-1",
        "sender_email": "Alice@Example.com",
        "recipient_email": "Bob@Example.com",
        "body": "Keep  TWO spaces exactly.",
    }
    values.update(overrides)
    return RelayMessageInput(**values)


def _service(
    runner: RecordingQueryRunner,
    safety: _Safety | None = None,
) -> RelayMessageService:
    return RelayMessageService(
        runner,
        settings=test_settings(),
        safety_provider=safety or _Safety(),
        clock=lambda: NOW,
    )


class RelayMessageServiceTest(unittest.TestCase):
    def test_policy_resolves_unique_emails_and_preserves_exact_body(self) -> None:
        runner = RecordingQueryRunner(results=[[_identity_row()]])
        safety = _Safety()

        result = _service(runner, safety).check_policy(_message(), robot_id="robot-1")

        self.assertTrue(result.allowed)
        self.assertEqual(result.sender_person_id, "person-alice")
        self.assertEqual(result.recipient_person_id, "person-bob")
        self.assertEqual(safety.bodies, ["Keep  TWO spaces exactly."])
        self.assertEqual(runner.queries[0].parameters["sender_email"], "alice@example.com")
        self.assertIn("size(senders) = 1", runner.queries[0].query)
        self.assertIn("sender <> recipient", runner.queries[0].query)

    def test_rejected_policy_is_not_persisted(self) -> None:
        runner = RecordingQueryRunner(results=[[_identity_row()]])
        safety = _Safety(allowed=False, reason="Not allowed.")

        with self.assertRaisesRegex(ValueError, "Not allowed"):
            _service(runner, safety).create_confirmed(_message(), robot_id="robot-1")

        self.assertEqual(len(runner.queries), 1)

    def test_confirmed_create_rechecks_policy_and_applies_limits(self) -> None:
        status_row = {
            **_identity_row(),
            "message_id": "relay-1",
            "assigned_robot_id": "robot-1",
            "status": "pending",
            "created_at": NOW.isoformat(),
            "deliver_after": NOW.isoformat(),
            "expires_at": "2026-08-22T15:00:00+00:00",
            "updated_at": NOW.isoformat(),
        }
        runner = RecordingQueryRunner(results=[[_identity_row()], [status_row]])

        with patch(
            "tailwag_memory.relay_messages.validate_input",
            wraps=validate_input,
        ) as validation:
            result = _service(runner).create_confirmed(_message(), robot_id="robot-1")

        self.assertEqual(result.status, "pending")
        validation.assert_called_once()
        query = runner.queries[1]
        self.assertEqual(query.parameters["body"], "Keep  TWO spaces exactly.")
        self.assertEqual(query.parameters["max_pending_per_pair"], 3)
        self.assertEqual(query.parameters["max_sends_per_day"], 5)
        self.assertIn("SET sender._relay_create_lock", query.query)
        self.assertIn("REMOVE sender._relay_create_lock", query.query)
        self.assertNotIn("relay_lock_version", query.query)
        self.assertLess(
            query.query.index("SET sender._relay_create_lock"),
            query.query.index("pending.status"),
        )
        self.assertIn("SENT_RELAY", query.query)
        self.assertIn("FOR_RECIPIENT", query.query)
        self.assertIn("ASSIGNED_TO", query.query)

    def test_explicit_expiry_may_only_shorten_thirty_day_default(self) -> None:
        too_late = "2026-08-23T15:00:00+00:00"

        with self.assertRaisesRegex(ValueError, "more than 30 days"):
            _service(RecordingQueryRunner()).check_policy(
                _message(expires_at=too_late),
                robot_id="robot-1",
            )

    def test_package_boundary_rejects_raw_media_and_unbounded_metadata(self) -> None:
        service = _service(RecordingQueryRunner())

        for key in ("raw_audio", "confidence", "audio_url", "data_url", "crop", "preview_image"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "raw media"):
                    service.check_policy(
                        _message(metadata={"nested": {key: "blocked"}}),
                        robot_id="robot-1",
                    )
        with self.assertRaisesRegex(ValueError, "at most 4096"):
            service.check_policy(
                _message(metadata={"note": "x" * 5000}),
                robot_id="robot-1",
            )

    def test_claim_returns_body_free_envelope_and_atomic_token(self) -> None:
        row = {
            **_identity_row(),
            "message_id": "relay-1",
            "assigned_robot_id": "robot-1",
            "created_at": NOW.isoformat(),
            "deliver_after": NOW.isoformat(),
            "expires_at": "2026-08-01T00:00:00+00:00",
            "status": "claimed",
            "claim_token": "claim-1",
        }
        runner = RecordingQueryRunner(results=[[row]])

        envelope = _service(runner).claim_next_envelope(
            recipient_email="BOB@example.com",
            robot_id="robot-1",
        )

        self.assertIsNotNone(envelope)
        assert envelope is not None
        self.assertEqual(envelope.claim_token, "claim-1")
        self.assertFalse(hasattr(envelope, "body"))
        self.assertNotIn("message.body AS body", runner.queries[0].query)
        query = runner.queries[0].query
        self.assertIn("SET robot._relay_claim_lock", query)
        self.assertIn("SET message._relay_write_lock", query)
        self.assertEqual(query.count("message.claim_token = randomUUID()"), 1)
        self.assertIn("REMOVE robot._relay_claim_lock", query)
        self.assertIn("REMOVE locked_message._relay_write_lock", query)
        self.assertNotIn("relay_claim_lock_version", query)
        self.assertLess(
            query.index("SET message._relay_write_lock"),
            query.index("candidate.message.status"),
        )

    def test_permission_requires_recipient_and_is_only_body_release(self) -> None:
        runner = RecordingQueryRunner(
            results=[[
                {
                    "message_id": "relay-1",
                    "status": "permission_granted",
                    "body": "Exact body.",
                }
            ]]
        )

        result = _service(runner).grant_permission(
            "relay-1",
            claim_token="claim-1",
            recipient_email="bob@example.com",
            robot_id="robot-1",
        )

        self.assertEqual(result.body, "Exact body.")
        query = runner.queries[0]
        self.assertIn("message.status = $status_from", query.query)
        self.assertLess(
            query.query.index("SET message._relay_write_lock"),
            query.query.index("message.status = $status_from"),
        )
        self.assertIn("REMOVE message._relay_write_lock", query.query)
        self.assertEqual(query.parameters["status_from"], "claimed")
        self.assertEqual(query.parameters["recipient_email"], "bob@example.com")

    def test_begin_and_complete_enforce_order_with_compare_and_set(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"message_id": "relay-1", "status": "delivering"}],
                [{"message_id": "relay-1", "status": "delivered"}],
            ]
        )
        service = _service(runner)

        started = service.begin_delivery("relay-1", claim_token="claim-1", robot_id="robot-1")
        completed = service.complete_delivery("relay-1", claim_token="claim-1", robot_id="robot-1")

        self.assertEqual(started.status, "delivering")
        self.assertEqual(completed.status, "delivered")
        self.assertEqual(runner.queries[0].parameters["status_from"], "permission_granted")
        self.assertEqual(runner.queries[1].parameters["status_from"], "delivering")

    def test_failure_after_audio_start_is_terminal_uncertain(self) -> None:
        runner = RecordingQueryRunner(
            results=[[{"message_id": "relay-1", "status": "delivery_uncertain"}]]
        )

        result = _service(runner).record_playback_failure(
            "relay-1",
            claim_token="claim-1",
            robot_id="robot-1",
            reason="device disconnected",
            audio_started=True,
        )

        self.assertEqual(result.status, "delivery_uncertain")
        self.assertEqual(runner.queries[0].parameters["status"], "delivery_uncertain")
        self.assertTrue(runner.queries[0].parameters["audio_started"])

    def test_failure_before_audio_start_returns_to_pending(self) -> None:
        runner = RecordingQueryRunner(results=[[{"message_id": "relay-1", "status": "pending"}]])

        result = _service(runner).record_playback_failure(
            "relay-1",
            claim_token="claim-1",
            robot_id="robot-1",
            reason="TTS unavailable",
            audio_started=False,
        )

        self.assertEqual(result.status, "pending")
        self.assertEqual(runner.queries[0].parameters["status"], "pending")

    def test_sender_status_never_projects_body_and_includes_failures(self) -> None:
        runner = RecordingQueryRunner(
            results=[[
                {
                    **_identity_row(),
                    "message_id": "relay-1",
                    "assigned_robot_id": "robot-1",
                    "status": "delivery_uncertain",
                    "last_failure_reason": "device disconnected",
                    "last_failure_at": NOW.isoformat(),
                }
            ]]
        )

        statuses = _service(runner).list_sender_statuses(
            sender_email="alice@example.com",
            robot_id="robot-1",
        )

        self.assertEqual(statuses[0].status, "delivery_uncertain")
        self.assertEqual(statuses[0].last_failure_reason, "device disconnected")
        self.assertNotIn("message.body", runner.queries[0].query)

    def test_maintenance_expires_releases_and_marks_stale_delivery_uncertain(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{
                    "expired_count": 2,
                    "claims_released_count": 1,
                    "uncertain_count": 1,
                }],
            ]
        )

        result = _service(runner).run_maintenance(claim_timeout_seconds=120)

        self.assertEqual(result.expired_count, 2)
        self.assertEqual(result.claims_released_count, 1)
        self.assertEqual(result.uncertain_count, 1)
        self.assertEqual(len(runner.queries), 1)
        query = runner.queries[0].query
        self.assertIn("delivery_uncertain", query)
        self.assertIn("ORDER BY elementId(message)", query)
        self.assertLess(
            query.index("SET message._relay_write_lock"),
            query.index("message.status IN"),
        )
        self.assertIn("REMOVE message._relay_write_lock", query)
        self.assertTrue(
            all("REMOVE message.body" not in recorded.query for recorded in runner.queries)
        )

    def test_all_state_transitions_lock_recheck_and_cleanup_in_one_query(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"message_id": "relay-1", "status": "permission_granted", "body": "body"}],
                [{"message_id": "relay-1", "status": "declined"}],
                [{"message_id": "relay-1", "status": "pending"}],
                [{"message_id": "relay-1", "status": "delivering"}],
                [{"message_id": "relay-1", "status": "delivered"}],
                [{"message_id": "relay-1", "status": "pending"}],
            ]
        )
        service = _service(runner)

        service.grant_permission(
            "relay-1",
            claim_token="claim-1",
            recipient_email="bob@example.com",
            robot_id="robot-1",
        )
        service.decline(
            "relay-1",
            claim_token="claim-1",
            recipient_email="bob@example.com",
            robot_id="robot-1",
        )
        service.snooze(
            "relay-1",
            claim_token="claim-1",
            recipient_email="bob@example.com",
            robot_id="robot-1",
            deliver_after="2026-07-23T16:00:00+00:00",
        )
        service.begin_delivery("relay-1", claim_token="claim-1", robot_id="robot-1")
        service.complete_delivery("relay-1", claim_token="claim-1", robot_id="robot-1")
        service.record_playback_failure(
            "relay-1",
            claim_token="claim-1",
            robot_id="robot-1",
            reason="speaker unavailable",
            audio_started=False,
        )

        self.assertEqual(len(runner.queries), 6)
        for recorded in runner.queries:
            with self.subTest(query=recorded.query):
                self.assertIn("SET message._relay_write_lock", recorded.query)
                self.assertIn("REMOVE message._relay_write_lock", recorded.query)
                self.assertLess(
                    recorded.query.index("SET message._relay_write_lock"),
                    recorded.query.index("message.status ="),
                )
                self.assertNotIn("REMOVE message.body", recorded.query)


if __name__ == "__main__":
    unittest.main()
