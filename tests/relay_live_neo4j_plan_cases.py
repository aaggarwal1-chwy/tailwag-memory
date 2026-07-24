"""Index-plan and retained-volume cases for the live Neo4j relay suite."""

from __future__ import annotations

from datetime import timedelta
import unittest

from tailwag_memory.relay_messages import RelayMessageService

from tests.helpers import RecordingQueryRunner
from tests.relay_live_neo4j_support import (
    AllowSafetyProvider,
    LIVE_TERMINAL_VOLUME,
    LIVE_VOLUME_ENABLED,
)


class RelayLiveNeo4jPlanCases:
    def test_delivery_lookup_plan_uses_composite_relay_index(self) -> None:
        recorded = self._record_claim_query(
            robot_id=self._id("plan-robot"),
            recipient_email=f"{self.prefix}-plan-recipient@example.test",
        )
        plan = self._explain(recorded.query, recorded.parameters)

        rendered = self._render_plan(plan)
        self.assertIn("NodeIndexSeek", rendered)
        self.assertIn("assigned_robot_id", rendered)
        self.assertIn("deliver_after", rendered)

    def test_maintenance_plan_uses_relay_status_index(self) -> None:
        recorded = self._record_maintenance_query()

        plan = self._explain(recorded.query, recorded.parameters)
        rendered = self._render_plan(plan)
        self.assertIn("NodeIndexSeek", rendered)
        self.assertIn("RelayMessage", rendered)
        self.assertIn("status", rendered)

    @unittest.skipUnless(
        LIVE_VOLUME_ENABLED,
        "set TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=1 for retained-volume PROFILE",
    )
    def test_terminal_volume_does_not_expand_pending_delivery_candidates(self) -> None:
        robot_id = self._id("volume-robot")
        recipient_email = f"{self.prefix}-volume-recipient@example.test"
        self.runner.run(
            "CREATE (:Robot {id: $robot_id, display_name: 'Volume Robot'})",
            {"robot_id": robot_id},
        )
        recorded = self._record_claim_query(
            robot_id=robot_id,
            recipient_email=recipient_email,
        )
        baseline = self._profile(recorded.query, recorded.parameters)

        terminal_ids = [
            self._id(f"retained-terminal-{index}")
            for index in range(LIVE_TERMINAL_VOLUME)
        ]
        self.runner.run(
            """
            MATCH (robot:Robot {id: $robot_id})
            UNWIND $message_ids AS message_id
            CREATE (message:RelayMessage {
              id: message_id,
              status: 'delivered',
              assigned_robot_id: $robot_id,
              created_at: $created_at,
              deliver_after: $deliver_after,
              expires_at: $expires_at,
              body: 'retained terminal body'
            })
            CREATE (message)-[:ASSIGNED_TO]->(robot)
            """,
            {
                "message_ids": terminal_ids,
                "robot_id": robot_id,
                "created_at": (self.now - timedelta(days=2)).isoformat(),
                "deliver_after": (self.now - timedelta(days=2)).isoformat(),
                "expires_at": (self.now - timedelta(days=1)).isoformat(),
            },
        )
        retained = self._profile(recorded.query, recorded.parameters)

        baseline_seek = self._find_profile_operator(baseline, "NodeIndexSeek")
        retained_seek = self._find_profile_operator(retained, "NodeIndexSeek")
        self.assertIsNotNone(baseline_seek)
        self.assertIsNotNone(retained_seek)
        assert baseline_seek is not None and retained_seek is not None
        self.assertEqual(getattr(baseline_seek, "rows", None), 0)
        self.assertEqual(getattr(retained_seek, "rows", None), 0)
        self.assertLessEqual(
            int(getattr(retained_seek, "db_hits", 0)),
            int(getattr(baseline_seek, "db_hits", 0)) + 1,
        )

    @unittest.skipUnless(
        LIVE_VOLUME_ENABLED,
        "set TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=1 for retained-volume PROFILE",
    )
    def test_terminal_volume_does_not_expand_maintenance_candidates(self) -> None:
        recorded = self._record_maintenance_query()
        baseline = self._profile(recorded.query, recorded.parameters)

        terminal_ids = [
            self._id(f"maintenance-terminal-{index}")
            for index in range(LIVE_TERMINAL_VOLUME)
        ]
        self.runner.run(
            """
            UNWIND $message_ids AS message_id
            CREATE (:RelayMessage {
              id: message_id,
              status: 'delivered',
              assigned_robot_id: $robot_id,
              created_at: $created_at,
              deliver_after: $deliver_after,
              expires_at: $expires_at,
              body: 'retained terminal body'
            })
            """,
            {
                "message_ids": terminal_ids,
                "robot_id": self._id("maintenance-volume-robot"),
                "created_at": (self.now - timedelta(days=2)).isoformat(),
                "deliver_after": (self.now - timedelta(days=2)).isoformat(),
                "expires_at": (self.now - timedelta(days=1)).isoformat(),
            },
        )
        retained = self._profile(recorded.query, recorded.parameters)

        baseline_seek = self._find_profile_operator(baseline, "NodeIndexSeek")
        retained_seek = self._find_profile_operator(retained, "NodeIndexSeek")
        self.assertIsNotNone(baseline_seek)
        self.assertIsNotNone(retained_seek)
        assert baseline_seek is not None and retained_seek is not None
        self.assertIn("RelayMessage", self._render_plan(retained_seek))
        self.assertIn("status", self._render_plan(retained_seek))
        self.assertEqual(getattr(baseline_seek, "rows", None), 0)
        self.assertEqual(getattr(retained_seek, "rows", None), 0)
        self.assertLessEqual(
            int(getattr(retained_seek, "db_hits", 0)),
            int(getattr(baseline_seek, "db_hits", 0)) + 1,
        )

        rows = self.runner.run(
            """
            MATCH (message:RelayMessage)
            WHERE message.id IN $message_ids
            RETURN count(message) AS total_count,
                   sum(CASE WHEN message.status = 'delivered' THEN 1 ELSE 0 END)
                     AS delivered_count,
                   sum(CASE WHEN message.body = 'retained terminal body' THEN 1 ELSE 0 END)
                     AS retained_body_count
            """,
            {"message_ids": terminal_ids},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_count"], LIVE_TERMINAL_VOLUME)
        self.assertEqual(rows[0]["delivered_count"], LIVE_TERMINAL_VOLUME)
        self.assertEqual(rows[0]["retained_body_count"], LIVE_TERMINAL_VOLUME)

    def _record_claim_query(self, *, robot_id: str, recipient_email: str) -> object:
        recorder = RecordingQueryRunner()
        RelayMessageService(
            recorder,
            settings=self.settings,
            safety_provider=AllowSafetyProvider(),
            clock=lambda: self.now,
        ).claim_next_envelope(
            recipient_email=recipient_email,
            robot_id=robot_id,
        )
        self.assertEqual(len(recorder.queries), 1)
        return recorder.queries[0]

    def _record_maintenance_query(self) -> object:
        recorder = RecordingQueryRunner()
        RelayMessageService(
            recorder,
            settings=self.settings,
            safety_provider=AllowSafetyProvider(),
            clock=lambda: self.now,
        ).run_maintenance(
            now=self.now.isoformat(),
            claim_timeout_seconds=120,
        )
        self.assertEqual(len(recorder.queries), 1)
        return recorder.queries[0]
