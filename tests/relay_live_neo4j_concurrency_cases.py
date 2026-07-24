"""Schema and concurrency cases for the live Neo4j relay suite."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from neo4j.exceptions import ConstraintError

from tailwag_memory.models import RelayMessageInput
from tailwag_memory.relay_messages import RelayRateLimitError
from tailwag_memory.schema import initialize_schema

from tests.relay_live_neo4j_contention_support import (
    _assert_blocked_by_held_lock,
    _HeldNeo4jLock,
    _OperationBarrierRunner,
)


class RelayLiveNeo4jConcurrencyCases:
    def test_schema_is_idempotent_and_relay_indexes_are_online(self) -> None:
        initialize_schema(self.runner, self.settings.embedding_dimension)
        initialize_schema(self.runner, self.settings.embedding_dimension)

        constraints = self.runner.run(
            """
            SHOW CONSTRAINTS
            YIELD name, type, labelsOrTypes, properties
            WHERE name = 'relay_message_id'
            RETURN type, labelsOrTypes, properties
            """
        )
        indexes = self.runner.run(
            """
            SHOW INDEXES
            YIELD name, type, state, labelsOrTypes, properties
            WHERE name IN [
              'relay_message_status',
              'relay_message_delivery',
              'relay_message_expires_at'
            ]
            RETURN name, type, state, labelsOrTypes, properties
            ORDER BY name
            """
        )

        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0]["labelsOrTypes"], ["RelayMessage"])
        self.assertEqual(constraints[0]["properties"], ["id"])
        self.assertIn("UNIQUENESS", constraints[0]["type"])
        self.assertEqual(
            {
                row["name"]: (row["state"], row["labelsOrTypes"], row["properties"])
                for row in indexes
            },
            {
                "relay_message_delivery": (
                    "ONLINE",
                    ["RelayMessage"],
                    ["assigned_robot_id", "status", "deliver_after", "created_at"],
                ),
                "relay_message_expires_at": (
                    "ONLINE",
                    ["RelayMessage"],
                    ["expires_at"],
                ),
                "relay_message_status": ("ONLINE", ["RelayMessage"], ["status"]),
            },
        )

    def test_concurrent_duplicate_create_persists_one_message_and_cleans_locks(self) -> None:
        sender_id, recipient_id, robot_id = self._create_identities()
        message_id = self._id("duplicate-message")
        message = self._message(message_id)
        contenders = 2
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET sender._relay_create_lock = $lock_token",
            parties=contenders,
        )

        def create() -> object:
            service = self._service(runner=gated_runner)
            try:
                return service.create_confirmed(message, robot_id=robot_id)
            except Exception as exc:  # The losing uniqueness transaction is expected.
                return exc

        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (sender:Person {id: $sender_id})
            SET sender._relay_create_lock = $holder_token
            RETURN sender.id AS sender_id
            """,
            parameters={
                "sender_id": sender_id,
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=contenders) as executor:
            with lock_holder:
                futures = [executor.submit(create) for _ in range(contenders)]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]

        gated_runner.assert_full_contention(self)
        successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        self.assertEqual(len(successes), 1, outcomes)
        self.assertEqual(len(failures), 1, outcomes)
        self.assertIsInstance(failures[0], ConstraintError)
        rows = self.runner.run(
            """
            MATCH (message:RelayMessage {id: $message_id})
            OPTIONAL MATCH (sender:Person)-[sent:SENT_RELAY]->(message)
            OPTIONAL MATCH (message)-[recipient:FOR_RECIPIENT]->(:Person)
            OPTIONAL MATCH (message)-[assigned:ASSIGNED_TO]->(:Robot)
            RETURN count(DISTINCT message) AS messages,
                   count(DISTINCT sent) AS sent_edges,
                   count(DISTINCT recipient) AS recipient_edges,
                   count(DISTINCT assigned) AS assigned_edges,
                   message.body AS body,
                   message._relay_create_token AS message_lock
            """,
            {"message_id": message_id},
        )[0]
        self.assertEqual(
            (
                rows["messages"],
                rows["sent_edges"],
                rows["recipient_edges"],
                rows["assigned_edges"],
            ),
            (1, 1, 1, 1),
        )
        self.assertEqual(rows["body"], message.body)
        self.assertIsNone(rows["message_lock"])
        lock_rows = self.runner.run(
            """
            MATCH (sender:Person {id: $sender_id})
            MATCH (robot:Robot {id: $robot_id})
            RETURN sender._relay_create_lock AS sender_lock,
                   robot._relay_claim_lock AS robot_lock
            """,
            {"sender_id": sender_id, "robot_id": robot_id},
        )[0]
        self.assertIsNone(lock_rows["sender_lock"])
        self.assertIsNone(lock_rows["robot_lock"])
        self.assertIn(recipient_id, self.node_ids)

    def test_concurrent_unique_creates_enforce_pair_pending_limit(self) -> None:
        _, _, robot_id = self._create_identities()
        messages = [
            self._message(self._id(f"pair-limit-{index}"))
            for index in range(5)
        ]
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET sender._relay_create_lock = $lock_token",
            parties=len(messages),
        )

        def create(message: RelayMessageInput) -> object:
            try:
                return self._service(runner=gated_runner).create_confirmed(
                    message,
                    robot_id=robot_id,
                )
            except Exception as exc:
                return exc

        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (sender:Person {id: $sender_id})
            SET sender._relay_create_lock = $holder_token
            RETURN sender.id AS sender_id
            """,
            parameters={
                "sender_id": f"{self.prefix}-sender",
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=len(messages)) as executor:
            with lock_holder:
                futures = [
                    executor.submit(create, message) for message in messages
                ]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]

        gated_runner.assert_full_contention(self)
        successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        self.assertEqual(len(successes), 3, outcomes)
        self.assertTrue(
            all(isinstance(failure, RelayRateLimitError) for failure in failures),
            outcomes,
        )
        rows = self.runner.run(
            """
            MATCH (:Person {id: $sender_id})-[:SENT_RELAY]->(message:RelayMessage)
            WHERE message.id IN $message_ids
            RETURN count(message) AS messages,
                   collect(message.status) AS statuses
            """,
            {
                "sender_id": f"{self.prefix}-sender",
                "message_ids": [message.id for message in messages],
            },
        )[0]
        self.assertEqual(rows["messages"], 3)
        self.assertEqual(rows["statuses"], ["pending"] * 3)
        lock = self.runner.run(
            """
            MATCH (sender:Person {id: $sender_id})
            RETURN sender._relay_create_lock AS create_lock
            """,
            {"sender_id": f"{self.prefix}-sender"},
        )[0]
        self.assertIsNone(lock["create_lock"])

    def test_concurrent_unique_creates_enforce_daily_sender_limit(self) -> None:
        _, _, robot_id = self._create_identities()
        daily_settings = replace(
            self.settings,
            relay_max_pending_per_pair=10,
            relay_max_sends_per_sender_per_day=5,
        )
        messages = [
            self._message(self._id(f"daily-limit-{index}"))
            for index in range(8)
        ]
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET sender._relay_create_lock = $lock_token",
            parties=len(messages),
        )

        def create(message: RelayMessageInput) -> object:
            try:
                return self._service(
                    settings=daily_settings,
                    runner=gated_runner,
                ).create_confirmed(
                    message,
                    robot_id=robot_id,
                )
            except Exception as exc:
                return exc

        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (sender:Person {id: $sender_id})
            SET sender._relay_create_lock = $holder_token
            RETURN sender.id AS sender_id
            """,
            parameters={
                "sender_id": f"{self.prefix}-sender",
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=len(messages)) as executor:
            with lock_holder:
                futures = [
                    executor.submit(create, message) for message in messages
                ]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]

        gated_runner.assert_full_contention(self)
        successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        self.assertEqual(len(successes), 5, outcomes)
        self.assertTrue(
            all(isinstance(failure, RelayRateLimitError) for failure in failures),
            outcomes,
        )
        row = self.runner.run(
            """
            MATCH (sender:Person {id: $sender_id})-[:SENT_RELAY]->(message:RelayMessage)
            WHERE message.id IN $message_ids
            RETURN count(message) AS messages,
                   sender._relay_create_lock AS create_lock
            """,
            {
                "sender_id": f"{self.prefix}-sender",
                "message_ids": [message.id for message in messages],
            },
        )[0]
        self.assertEqual(row["messages"], 5)
        self.assertIsNone(row["create_lock"])

    def test_concurrent_claim_returns_one_body_free_envelope(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("claim-message"), body="Exact  private body.")
        self._service().create_confirmed(message, robot_id=robot_id)
        contenders = 4
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="SET robot._relay_claim_lock = randomUUID()",
            parties=contenders,
        )

        def claim() -> object:
            try:
                return self._service(runner=gated_runner).claim_next_envelope(
                    recipient_email=message.recipient_email,
                    robot_id=robot_id,
                )
            except Exception as exc:
                return exc

        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (robot:Robot {id: $robot_id})
            SET robot._relay_claim_lock = $holder_token
            RETURN robot.id AS robot_id
            """,
            parameters={
                "robot_id": robot_id,
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=contenders) as executor:
            with lock_holder:
                futures = [executor.submit(claim) for _ in range(contenders)]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]

        gated_runner.assert_full_contention(self)
        errors = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        self.assertEqual(errors, [])
        envelopes = [outcome for outcome in outcomes if outcome is not None]
        self.assertEqual(len(envelopes), 1, outcomes)
        envelope = envelopes[0]
        self.assertFalse(hasattr(envelope, "body"))
        self.assertTrue(envelope.claim_token)
        stored = self._message_properties(message.id)
        self.assertEqual(stored["status"], "claimed")
        self.assertEqual(stored["claim_token"], envelope.claim_token)
        self.assertEqual(stored["body"], message.body)
        self.assertNotIn("_relay_write_lock", stored)

    def test_concurrent_recipient_transitions_have_one_winner(self) -> None:
        _, _, robot_id = self._create_identities()
        message = self._message(self._id("transition-message"))
        service = self._service()
        service.create_confirmed(message, robot_id=robot_id)
        envelope = service.claim_next_envelope(
            recipient_email=message.recipient_email,
            robot_id=robot_id,
        )
        self.assertIsNotNone(envelope)
        assert envelope is not None
        contenders = 2
        gated_runner = _OperationBarrierRunner(
            self.runner,
            query_marker="AND message.status = $status_from",
            parties=contenders,
        )

        def grant() -> object:
            return self._service(runner=gated_runner).grant_permission(
                message.id,
                claim_token=envelope.claim_token,
                recipient_email=message.recipient_email,
                robot_id=robot_id,
            )

        def decline() -> object:
            return self._service(runner=gated_runner).decline(
                message.id,
                claim_token=envelope.claim_token,
                recipient_email=message.recipient_email,
                robot_id=robot_id,
            )

        lock_holder = _HeldNeo4jLock(
            self.runner._driver,
            query="""
            MATCH (message:RelayMessage {id: $message_id})
            SET message._relay_write_lock = $holder_token
            RETURN message.id AS message_id
            """,
            parameters={
                "message_id": message.id,
                "holder_token": "live-test-lock-holder",
            },
        )
        with ThreadPoolExecutor(max_workers=contenders) as executor:
            with lock_holder:
                futures = [executor.submit(grant), executor.submit(decline)]
                _assert_blocked_by_held_lock(self, gated_runner, futures)
            outcomes = [future.result() for future in futures]

        gated_runner.assert_full_contention(self)
        statuses = sorted(outcome.status for outcome in outcomes)
        self.assertIn(
            statuses,
            [["conflict", "declined"], ["conflict", "permission_granted"]],
        )
        stored = self._message_properties(message.id)
        self.assertIn(stored["status"], {"declined", "permission_granted"})
        self.assertEqual(stored["body"], message.body)
        self.assertNotIn("_relay_write_lock", stored)
