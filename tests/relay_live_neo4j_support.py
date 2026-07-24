"""Shared harness for opt-in relay tests against a disposable Neo4j database.

Enabling the suite requires explicit connection credentials and
``TAILWAG_LIVE_NEO4J_TEST_DATABASE=I_UNDERSTAND_THIS_MUTATES_SCHEMA`` because
the harness initializes schema and deletes its exact-ID fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.models import RelayMessageInput
from tailwag_memory.relay_messages import RelayMessageService
from tailwag_memory.relay_policy import RelaySafetyDecision
from tailwag_memory.schema import initialize_schema

from tests.helpers import test_settings


_LIVE_NEO4J_REQUESTED = os.environ.get(
    "TAILWAG_RUN_LIVE_NEO4J_TESTS", ""
).casefold() in {
    "1",
    "true",
    "yes",
}
_LIVE_NEO4J_ACKNOWLEDGEMENT = "I_UNDERSTAND_THIS_MUTATES_SCHEMA"
if _LIVE_NEO4J_REQUESTED:
    missing_live_settings = [
        name
        for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")
        if not os.environ.get(name, "").strip()
    ]
    if missing_live_settings:
        raise RuntimeError(
            "Live Neo4j relay tests require explicit non-empty settings: "
            + ", ".join(missing_live_settings)
        )
    if (
        os.environ.get("TAILWAG_LIVE_NEO4J_TEST_DATABASE")
        != _LIVE_NEO4J_ACKNOWLEDGEMENT
    ):
        raise RuntimeError(
            "Live Neo4j relay tests mutate schema; set "
            "TAILWAG_LIVE_NEO4J_TEST_DATABASE="
            f"{_LIVE_NEO4J_ACKNOWLEDGEMENT} only for a disposable test database"
        )

LIVE_NEO4J_ENABLED = _LIVE_NEO4J_REQUESTED
LIVE_VOLUME_ENABLED = os.environ.get(
    "TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS", ""
).casefold() in {"1", "true", "yes"}


def _terminal_volume() -> int:
    try:
        configured = int(
            os.environ.get("TAILWAG_LIVE_NEO4J_TERMINAL_VOLUME", "250")
        )
    except ValueError:
        return 250
    return max(1, min(5000, configured))


LIVE_TERMINAL_VOLUME = _terminal_volume()


class AllowSafetyProvider:
    def screen(self, *, body: str) -> RelaySafetyDecision:
        return RelaySafetyDecision(allowed=True)


class RelayLiveNeo4jHarness:
    """Provide isolated IDs, exact-ID cleanup, and live-query helpers."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.settings = test_settings(
            neo4j_uri=os.environ["NEO4J_URI"],
            neo4j_user=os.environ["NEO4J_USER"],
            neo4j_password=os.environ["NEO4J_PASSWORD"],
            relay_max_pending_per_pair=3,
            relay_max_sends_per_sender_per_day=20,
        )
        cls.runner = Neo4jQueryRunner(cls.settings)
        cls.runner.run("RETURN 1 AS ready")
        initialize_schema(cls.runner, cls.settings.embedding_dimension)
        cls.runner.run("CALL db.awaitIndexes(60)")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runner.close()
        super().tearDownClass()

    def setUp(self) -> None:
        self.prefix = f"tailwag-live-relay-{uuid4().hex}"
        self.node_ids: set[str] = set()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self) -> None:
        if self.node_ids:
            self.runner.run(
                "MATCH (node) WHERE node.id IN $node_ids DETACH DELETE node",
                {"node_ids": sorted(self.node_ids)},
            )

    def _id(self, suffix: str) -> str:
        identifier = f"{self.prefix}-{suffix}"
        self.node_ids.add(identifier)
        return identifier

    def _create_identities(self) -> tuple[str, str, str]:
        sender_id = self._id("sender")
        recipient_id = self._id("recipient")
        robot_id = self._id("robot")
        sender_email = f"{self.prefix}-sender@example.test"
        recipient_email = f"{self.prefix}-recipient@example.test"
        self.runner.run(
            """
            CREATE (:Person {
              id: $sender_id,
              email: $sender_email,
              display_name: 'Live Sender',
              status: 'active'
            })
            CREATE (:Person {
              id: $recipient_id,
              email: $recipient_email,
              display_name: 'Live Recipient',
              status: 'active'
            })
            CREATE (:Robot {id: $robot_id, display_name: 'Live Robot'})
            """,
            {
                "sender_id": sender_id,
                "sender_email": sender_email,
                "recipient_id": recipient_id,
                "recipient_email": recipient_email,
                "robot_id": robot_id,
            },
        )
        self.sender_email = sender_email
        self.recipient_email = recipient_email
        return sender_id, recipient_id, robot_id

    def _message(
        self,
        message_id: str,
        *,
        body: str = "Live relay body.",
    ) -> RelayMessageInput:
        return RelayMessageInput(
            id=message_id,
            sender_email=self.sender_email,
            recipient_email=self.recipient_email,
            body=body,
            deliver_after=(self.now - timedelta(seconds=1)).isoformat(),
            expires_at=(self.now + timedelta(days=1)).isoformat(),
            metadata={"live_test": self.prefix},
        )

    def _service(
        self,
        *,
        clock=None,
        settings=None,
        runner=None,
    ) -> RelayMessageService:
        return RelayMessageService(
            runner or self.runner,
            settings=settings or self.settings,
            safety_provider=AllowSafetyProvider(),
            clock=clock or (lambda: self.now),
        )

    def _seed_message(
        self,
        suffix: str,
        *,
        status: str,
        expires_delta: int,
        claimed_delta: int | None = None,
        delivery_started_delta: int | None = None,
        claim_token: str | None = None,
    ) -> str:
        message_id = self._id(f"maintenance-{suffix}")
        properties = {
            "id": message_id,
            "body": f"body:{message_id}",
            "status": status,
            "assigned_robot_id": self._id(f"maintenance-robot-{suffix}"),
            "created_at": (self.now - timedelta(hours=1)).isoformat(),
            "updated_at": (self.now - timedelta(hours=1)).isoformat(),
            "deliver_after": (self.now - timedelta(hours=1)).isoformat(),
            "expires_at": (self.now + timedelta(seconds=expires_delta)).isoformat(),
        }
        if claimed_delta is not None:
            properties["claimed_at"] = (
                self.now + timedelta(seconds=claimed_delta)
            ).isoformat()
        if delivery_started_delta is not None:
            properties["delivery_started_at"] = (
                self.now + timedelta(seconds=delivery_started_delta)
            ).isoformat()
        if claim_token is not None:
            properties["claim_token"] = claim_token
        self.runner.run(
            "CREATE (message:RelayMessage) SET message = $properties",
            {"properties": properties},
        )
        return message_id

    def _message_properties(self, message_id: str) -> dict[str, object]:
        rows = self.runner.run(
            "MATCH (message:RelayMessage {id: $message_id}) "
            "RETURN properties(message) AS properties",
            {"message_id": message_id},
        )
        self.assertEqual(len(rows), 1)
        return dict(rows[0]["properties"])

    def _explain(self, query: str, parameters: dict[str, object]) -> object:
        with self.runner._driver.session() as session:
            result = session.run(f"EXPLAIN {query}", parameters)
            return result.consume().plan

    def _profile(self, query: str, parameters: dict[str, object]) -> object:
        with self.runner._driver.session() as session:
            result = session.run(f"PROFILE {query}", parameters)
            list(result)
            return result.consume().profile

    @classmethod
    def _find_profile_operator(cls, plan: object, operator_type: str) -> object | None:
        if str(getattr(plan, "operator_type", "")).startswith(operator_type):
            return plan
        for child in getattr(plan, "children", ()):
            found = cls._find_profile_operator(child, operator_type)
            if found is not None:
                return found
        return None

    @classmethod
    def _render_plan(cls, plan: object) -> str:
        if plan is None:
            return ""
        parts = [
            str(getattr(plan, "operator_type", "")),
            repr(getattr(plan, "arguments", {})),
            repr(getattr(plan, "identifiers", set())),
        ]
        for child in getattr(plan, "children", ()):
            parts.append(cls._render_plan(child))
        return "\n".join(parts)
