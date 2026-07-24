"""Opt-in live Neo4j races for pre-audio relay release behavior."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import unittest

from tests.relay_live_neo4j_contention_support import (
    _assert_blocked_by_held_lock,
    _HeldNeo4jLock,
    _OperationBarrierRunner,
)
from tests.relay_live_neo4j_support import (
    LIVE_NEO4J_ENABLED,
    RelayLiveNeo4jHarness,
)


@unittest.skipUnless(
    LIVE_NEO4J_ENABLED,
    "set TAILWAG_RUN_LIVE_NEO4J_TESTS=1 to run real-Neo4j relay tests",
)
class RelayPreAudioLiveNeo4jTest(RelayLiveNeo4jHarness, unittest.TestCase):
    def test_grant_racing_release_always_returns_message_to_pending(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("grant-release-race"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET message._relay_write_lock = randomUUID()",
            parties=2,
        )

        def grant() -> object:
            return self._service(runner=gated_runner).grant_permission(
                message.id,
                claim_token=envelope.claim_token,
                recipient_email=message.recipient_email,
                robot_id=robot_id,
            )

        def release() -> object:
            return self._service(runner=gated_runner).release_before_playback(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            )

        outcomes = self._run_contenders_with_message_lock(
            message_id=message.id,
            gated_runner=gated_runner,
            contenders=(grant, release),
        )

        self.assertIn(
            sorted(result.status for result in outcomes),
            [["conflict", "pending"], ["pending", "permission_granted"]],
        )
        stored = self._message_properties(message.id)
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["body"], message.body)
        self.assertNotIn("claim_token", stored)
        self.assertNotIn("claimed_at", stored)
        self.assertNotIn("permission_granted_at", stored)
        self.assertNotIn("delivery_started_at", stored)
        self.assertNotIn("_relay_write_lock", stored)

    def test_begin_racing_pre_audio_failure_always_returns_message_to_pending(
        self,
    ) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("begin-failure-race"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        service.grant_permission(
            message.id,
            claim_token=envelope.claim_token,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET message._relay_write_lock = randomUUID()",
            parties=2,
        )

        def begin() -> object:
            return self._service(runner=gated_runner).begin_delivery(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            )

        def fail_before_audio() -> object:
            return self._service(runner=gated_runner).record_playback_failure(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
                reason="TTS aborted before playback",
                audio_started=False,
            )

        outcomes = self._run_contenders_with_message_lock(
            message_id=message.id,
            gated_runner=gated_runner,
            contenders=(begin, fail_before_audio),
        )

        self.assertIn(
            sorted(result.status for result in outcomes),
            [["conflict", "pending"], ["delivering", "pending"]],
        )
        stored = self._message_properties(message.id)
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["body"], message.body)
        self.assertEqual(
            stored["last_failure_reason"],
            "TTS aborted before playback",
        )
        self.assertFalse(stored["last_failure_audio_started"])
        self.assertNotIn("claim_token", stored)
        self.assertNotIn("claimed_at", stored)
        self.assertNotIn("permission_granted_at", stored)
        self.assertNotIn("delivery_started_at", stored)
        self.assertNotIn("_relay_write_lock", stored)

    def test_begin_racing_release_has_one_winner_and_safe_compensation(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("begin-release-race"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        service.grant_permission(
            message.id,
            claim_token=envelope.claim_token,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET message._relay_write_lock = randomUUID()",
            parties=2,
        )

        def begin() -> object:
            return self._service(runner=gated_runner).begin_delivery(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            )

        def release() -> object:
            return self._service(runner=gated_runner).release_before_playback(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            )

        outcomes = self._run_contenders_with_message_lock(
            message_id=message.id,
            gated_runner=gated_runner,
            contenders=(begin, release),
        )

        statuses = sorted(result.status for result in outcomes)
        self.assertIn(
            statuses,
            [["conflict", "delivering"], ["conflict", "pending"]],
        )
        stored = self._message_properties(message.id)
        if stored["status"] == "delivering":
            compensated = service.record_playback_failure(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
                reason="shutdown_before_audio",
                audio_started=False,
            )
            self.assertEqual(compensated.status, "pending")
            stored = self._message_properties(message.id)
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["body"], message.body)
        self.assertNotIn("claim_token", stored)
        self.assertNotIn("_relay_write_lock", stored)

    def _run_contenders_with_message_lock(
        self,
        *,
        message_id: str,
        gated_runner: _OperationBarrierRunner,
        contenders: tuple[object, object],
    ) -> list[object]:
        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (message:RelayMessage {id: $message_id})
            SET message._relay_write_lock = $holder_token
            RETURN message.id AS message_id
            """,
            parameters={
                "message_id": message_id,
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            with lock_holder:
                futures = [executor.submit(contender) for contender in contenders]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]
        gated_runner.assert_full_contention(self)
        return outcomes


if __name__ == "__main__":
    unittest.main()
