from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from tailwag_memory.cli import main
from tailwag_memory.config import Settings
from tailwag_memory.slack_ingestion import SlackPollResult


class FakeRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def run(self, query: str, parameters: dict[str, object] | None = None) -> list[dict[str, object]]:
        self.queries.append((query, parameters))
        return []

    def close(self) -> None:
        self.closed = True


class CliTest(unittest.TestCase):
    def test_db_wipe_requires_confirmation(self) -> None:
        with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["db", "wipe"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("db wipe requires --yes", stderr.getvalue())
        runner_class.assert_not_called()

    def test_db_wipe_deletes_all_nodes_and_relationships(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
        )
        runner = FakeRunner(settings)

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(["db", "wipe", "--yes"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(runner.queries, [("MATCH (n) DETACH DELETE n", None)])
        self.assertTrue(runner.closed)
        self.assertIn("Neo4j data wiped.", stdout.getvalue())

    def test_slack_force_backfill_requires_backfill_hours(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["slack", "poll", "--channel", "C123", "--force-backfill", "--once"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--force-backfill requires --backfill-hours", stderr.getvalue())

    def test_slack_force_backfill_is_passed_to_poller(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            slack_bot_token="xoxb-test-token",
        )
        runner = FakeRunner(settings)
        poll_calls = []

        class FakePoller:
            def __init__(self, client, service, state_path, *, active_thread_hours: float) -> None:
                self.client = client
                self.service = service
                self.state_path = state_path
                self.active_thread_hours = active_thread_hours

            def poll_once(
                self,
                channel: str,
                *,
                backfill_hours: float | None,
                force_backfill: bool,
                history_limit: int,
                reply_limit: int,
            ) -> SlackPollResult:
                poll_calls.append(
                    {
                        "channel": channel,
                        "backfill_hours": backfill_hours,
                        "force_backfill": force_backfill,
                        "history_limit": history_limit,
                        "reply_limit": reply_limit,
                    }
                )
                return SlackPollResult(
                    channel=channel,
                    checked_threads=0,
                    ingested_threads=0,
                    latest_history_ts=None,
                    armed_without_backfill=True,
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.SlackWebApiClient", return_value=object()):
                    with patch("tailwag_memory.cli.EpisodeIngestionService", return_value=object()):
                        with patch("tailwag_memory.cli.SlackMemoryPoller", FakePoller):
                            stdout = StringIO()
                            with redirect_stdout(stdout):
                                exit_code = main(
                                    [
                                        "slack",
                                        "poll",
                                        "--channel",
                                        "C123",
                                        "--once",
                                        "--backfill-hours",
                                        "10",
                                        "--force-backfill",
                                    ]
                                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            poll_calls,
            [
                {
                    "channel": "C123",
                    "backfill_hours": 10.0,
                    "force_backfill": True,
                    "history_limit": 200,
                    "reply_limit": 200,
                }
            ],
        )
        self.assertEqual(json.loads(stdout.getvalue())["channel"], "C123")

    def test_person_context_prints_synthesized_paragraph(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeContextService:
            def __init__(self, retrieval, provider) -> None:
                self.retrieval = retrieval
                self.provider = provider

            def context_for_person(
                self,
                person_id: str,
                limit: int = 10,
                semantic_scope: str | None = None,
            ) -> str:
                calls.append({"person_id": person_id, "limit": limit, "semantic_scope": semantic_scope})
                return "Jamie recently asked about chargers."

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.PersonContextSynthesisService", FakeContextService):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(["person", "context", "--person-id", "person_jamie", "--limit", "3"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [{"person_id": "person_jamie", "limit": 3, "semantic_scope": None}])
        self.assertIn("Jamie recently asked about chargers.", stdout.getvalue())
        self.assertTrue(runner.closed)

    def test_person_context_passes_semantic_scope(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeContextService:
            def __init__(self, retrieval, provider) -> None:
                self.retrieval = retrieval
                self.provider = provider

            def context_for_person(
                self,
                person_id: str,
                limit: int = 10,
                semantic_scope: str | None = None,
            ) -> str:
                calls.append({"person_id": person_id, "limit": limit, "semantic_scope": semantic_scope})
                return "Jamie recently asked about chargers."

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.PersonContextSynthesisService", FakeContextService):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "person",
                                "context",
                                "--person-id",
                                "person_jamie",
                                "--limit",
                                "3",
                                "--semantic-scope",
                                "chargers",
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [{"person_id": "person_jamie", "limit": 3, "semantic_scope": "chargers"}])
        self.assertIn("Jamie recently asked about chargers.", stdout.getvalue())
        self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
