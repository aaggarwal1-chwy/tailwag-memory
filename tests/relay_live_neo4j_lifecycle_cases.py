"""Lifecycle durability cases for the live Neo4j relay suite."""

from __future__ import annotations

from datetime import timedelta


class RelayLiveNeo4jLifecycleCases:
    def test_wrong_robot_cannot_release_body(self) -> None:
        _, _, robot_id = self._create_identities()
        service, message_id, claim_token, body = self._claimed_message(robot_id)

        result = service.grant_permission(
            message_id,
            claim_token=claim_token,
            recipient_email=self.recipient_email,
            robot_id=self._id("wrong-robot"),
        )

        self._assert_body_release_denied(result, message_id=message_id, body=body)

    def test_wrong_recipient_cannot_release_body(self) -> None:
        _, _, robot_id = self._create_identities()
        service, message_id, claim_token, body = self._claimed_message(robot_id)

        result = service.grant_permission(
            message_id,
            claim_token=claim_token,
            recipient_email=f"{self.prefix}-wrong-recipient@example.test",
            robot_id=robot_id,
        )

        self._assert_body_release_denied(result, message_id=message_id, body=body)

    def test_stale_claim_token_cannot_release_body(self) -> None:
        _, _, robot_id = self._create_identities()
        service, message_id, _, body = self._claimed_message(robot_id)

        result = service.grant_permission(
            message_id,
            claim_token="stale-claim-token",
            recipient_email=self.recipient_email,
            robot_id=robot_id,
        )

        self._assert_body_release_denied(result, message_id=message_id, body=body)

    def test_archived_identity_cannot_release_body(self) -> None:
        _, recipient_id, robot_id = self._create_identities()
        service, message_id, claim_token, body = self._claimed_message(robot_id)
        self.runner.run(
            "MATCH (recipient:Person {id: $recipient_id}) "
            "SET recipient.status = 'archived'",
            {"recipient_id": recipient_id},
        )

        result = service.grant_permission(
            message_id,
            claim_token=claim_token,
            recipient_email=self.recipient_email,
            robot_id=robot_id,
        )

        self._assert_body_release_denied(result, message_id=message_id, body=body)

    def test_expired_claim_cannot_release_body(self) -> None:
        _, _, robot_id = self._create_identities()
        service, message_id, claim_token, body = self._claimed_message(robot_id)
        self.runner.run(
            "MATCH (message:RelayMessage {id: $message_id}) "
            "SET message.expires_at = $expires_at",
            {
                "message_id": message_id,
                "expires_at": (self.now - timedelta(seconds=1)).isoformat(),
            },
        )

        result = service.grant_permission(
            message_id,
            claim_token=claim_token,
            recipient_email=self.recipient_email,
            robot_id=robot_id,
        )

        self._assert_body_release_denied(result, message_id=message_id, body=body)

    def test_maintenance_is_idempotent_and_never_removes_bodies(self) -> None:
        expired_id = self._seed_message("expired", status="pending", expires_delta=-10)
        released_id = self._seed_message(
            "released",
            status="claimed",
            expires_delta=600,
            claimed_delta=-300,
            claim_token="stale-claim",
        )
        uncertain_id = self._seed_message(
            "uncertain",
            status="delivering",
            expires_delta=-10,
            claimed_delta=-400,
            delivery_started_delta=-300,
            claim_token="delivery-claim",
        )
        recent_claim_id = self._seed_message(
            "recent-claim",
            status="claimed",
            expires_delta=600,
            claimed_delta=-30,
            claim_token="recent-claim",
        )
        future_pending_id = self._seed_message(
            "future-pending",
            status="pending",
            expires_delta=600,
        )
        service = self._service(clock=lambda: self.now)

        first = service.run_maintenance(
            now=self.now.isoformat(),
            claim_timeout_seconds=120,
        )
        second = service.run_maintenance(
            now=self.now.isoformat(),
            claim_timeout_seconds=120,
        )

        self.assertEqual(
            (first.expired_count, first.claims_released_count, first.uncertain_count),
            (1, 1, 1),
        )
        self.assertEqual(
            (second.expired_count, second.claims_released_count, second.uncertain_count),
            (0, 0, 0),
        )
        expired = self._message_properties(expired_id)
        released = self._message_properties(released_id)
        uncertain = self._message_properties(uncertain_id)
        recent_claim = self._message_properties(recent_claim_id)
        future_pending = self._message_properties(future_pending_id)
        self.assertEqual(expired["status"], "expired")
        self.assertNotIn("claim_token", expired)
        self.assertEqual(released["status"], "pending")
        self.assertNotIn("claim_token", released)
        self.assertEqual(uncertain["status"], "delivery_uncertain")
        self.assertEqual(uncertain["claim_token"], "delivery-claim")
        self.assertTrue(uncertain["last_failure_audio_started"])
        self.assertEqual(recent_claim["status"], "claimed")
        self.assertEqual(recent_claim["claim_token"], "recent-claim")
        self.assertEqual(future_pending["status"], "pending")
        for properties in (
            expired,
            released,
            uncertain,
            recent_claim,
            future_pending,
        ):
            self.assertEqual(properties["body"], f"body:{properties['id']}")
            self.assertNotIn("_relay_write_lock", properties)

    def test_pre_and_post_audio_failures_preserve_body_and_replay_safety(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("audio-failure-message"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        first_claim = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(first_claim)
        assert first_claim is not None
        service.grant_permission(
            message.id,
            claim_token=first_claim.claim_token,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        service.begin_delivery(
            message.id,
            claim_token=first_claim.claim_token,
            robot_id=robot_id,
        )

        before_audio = service.record_playback_failure(
            message.id,
            claim_token=first_claim.claim_token,
            robot_id=robot_id,
            reason="TTS unavailable",
            audio_started=False,
        )
        after_first_failure = self._message_properties(message.id)
        self.assertEqual(before_audio.status, "pending")
        self.assertNotIn("claim_token", after_first_failure)
        self.assertNotIn("delivery_started_at", after_first_failure)
        self.assertEqual(after_first_failure["body"], message.body)

        second_claim = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(second_claim)
        assert second_claim is not None
        self.assertNotEqual(second_claim.claim_token, first_claim.claim_token)
        service.grant_permission(
            message.id,
            claim_token=second_claim.claim_token,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        service.begin_delivery(
            message.id,
            claim_token=second_claim.claim_token,
            robot_id=robot_id,
        )
        after_audio = service.record_playback_failure(
            message.id,
            claim_token=second_claim.claim_token,
            robot_id=robot_id,
            reason="speaker disconnected",
            audio_started=True,
        )
        terminal = self._message_properties(message.id)
        self.assertEqual(after_audio.status, "delivery_uncertain")
        self.assertEqual(terminal["claim_token"], second_claim.claim_token)
        self.assertEqual(terminal["body"], message.body)
        self.assertEqual(terminal["attempt_count"], 2)
        self.assertTrue(terminal["last_failure_audio_started"])
        self.assertIsNone(
            service.claim_next_envelope(
                recipient_email=message.recipient_email,
                robot_id=robot_id,
            )
        )

    def test_terminal_delivery_history_is_invariant_under_retries_and_maintenance(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("terminal-message"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        permission = service.grant_permission(
            message.id,
            claim_token=envelope.claim_token,
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertEqual(permission.body, message.body)
        self.assertEqual(
            service.begin_delivery(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            ).status,
            "delivering",
        )
        self.assertEqual(
            service.complete_delivery(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            ).status,
            "delivered",
        )
        before = self._message_properties(message.id)

        retry_results = [
            service.complete_delivery(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
            ),
            service.decline(
                message.id,
                claim_token=envelope.claim_token,
                recipient_email=message.recipient_email,
                robot_id=robot_id,
            ),
            service.record_playback_failure(
                message.id,
                claim_token=envelope.claim_token,
                robot_id=robot_id,
                reason="late retry",
                audio_started=True,
            ),
        ]
        maintenance = service.run_maintenance(
            now=(self.now + timedelta(days=2)).isoformat(),
            claim_timeout_seconds=1,
        )
        after = self._message_properties(message.id)

        self.assertEqual([result.status for result in retry_results], ["conflict"] * 3)
        self.assertEqual(
            (
                maintenance.expired_count,
                maintenance.claims_released_count,
                maintenance.uncertain_count,
            ),
            (0, 0, 0),
        )
        self.assertEqual(after, before)
        self.assertEqual(after["body"], message.body)
        self.assertEqual(after["attempt_count"], 1)

    def _claimed_message(
        self,
        robot_id: str,
    ) -> tuple[object, str, str, str]:
        service = self._service()
        message = self._message(
            self._id("body-release-message"),
            body="Sensitive live relay body.",
        )
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        return service, message.id, envelope.claim_token, message.body

    def _assert_body_release_denied(
        self,
        result: object,
        *,
        message_id: str,
        body: str,
    ) -> None:
        self.assertEqual(getattr(result, "status"), "conflict")
        self.assertIsNone(getattr(result, "body"))
        stored = self._message_properties(message_id)
        self.assertEqual(stored["status"], "claimed")
        self.assertEqual(stored["body"], body)
        self.assertNotIn("_relay_write_lock", stored)
