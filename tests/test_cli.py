from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tailwag_memory.cli import main
from tailwag_memory.config import Settings
from tailwag_memory.models import (
    EpisodeMemoryExtractionResult,
    EpisodeRecordResult,
    MemoryConsolidationResult,
    PersonMemoryConsolidationResult,
    PersonMemoryExtractionResult,
)
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
    def _episode_file(self, tmp: str) -> str:
        path = Path(tmp) / "episode.json"
        path.write_text(
            json.dumps(
                {
                    "id": "episode_1",
                    "episode_type": "conversation",
                    "start_time": "2026-06-18T10:00:00+00:00",
                    "end_time": None,
                    "summary": "Jamie likes robot demos.",
                    "transcript": "Jamie: I like robot demos.",
                    "retention_class": "standard",
                    "place": {"building_code": "MAIN", "room_id": "101"},
                    "participants": [{"id": "person_jamie", "role": "speaker"}],
                }
            )
        )
        return str(path)

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

    def test_slack_force_backfill_requires_once(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["slack", "poll", "--channel", "C123", "--force-backfill", "--backfill-hours", "1"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--force-backfill requires --once", stderr.getvalue())

    def test_slack_poll_missing_token_exits_before_db_runner(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            slack_bot_token=None,
        )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
                stderr = StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        main(["slack", "poll", "--channel", "C123", "--once"])

        self.assertEqual(raised.exception.code, 2)
        runner_class.assert_not_called()
        self.assertIn("SLACK_BOT_TOKEN is required", stderr.getvalue())

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

        class FakeMemoryClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                self.runner = runner_arg
                self.settings = settings_arg

        class FakePoller:
            def __init__(self, client, episode_recorder, state_path, *, active_thread_hours: float) -> None:
                self.client = client
                self.episode_recorder = episode_recorder
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
                extract_memory: bool,
            ) -> SlackPollResult:
                poll_calls.append(
                    {
                        "channel": channel,
                        "backfill_hours": backfill_hours,
                        "force_backfill": force_backfill,
                        "history_limit": history_limit,
                        "reply_limit": reply_limit,
                        "extract_memory": extract_memory,
                        "uses_memory_client": isinstance(self.episode_recorder, FakeMemoryClient),
                    }
                )
                return SlackPollResult(
                    channel=channel,
                    checked_threads=0,
                    ingested_threads=0,
                    latest_history_ts=None,
                    armed_without_backfill=True,
                    memory_extraction_enabled=extract_memory,
                    ingested_episode_ids=["episode_1"],
                    episode_records=[
                        EpisodeRecordResult(
                            episode_id="episode_1",
                            memory_results=[
                                PersonMemoryExtractionResult(
                                    person_id="person_jamie",
                                    created_memory_ids=["mem_1"],
                                )
                            ],
                        )
                    ],
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.SlackWebApiClient", return_value=object()):
                    with patch("tailwag_memory.cli.TailwagMemoryClient", FakeMemoryClient):
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
                    "extract_memory": True,
                    "uses_memory_client": True,
                }
            ],
        )
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["channel"], "C123")
        self.assertTrue(output["memory_extraction_enabled"])
        self.assertEqual(output["ingested_episode_ids"], ["episode_1"])
        self.assertEqual(output["episode_records"][0]["memory_results"][0]["created_memory_ids"], ["mem_1"])

    def test_slack_poll_can_skip_memory_extraction(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            slack_bot_token="xoxb-test-token",
        )
        runner = FakeRunner(settings)
        poll_calls = []

        class FakeMemoryClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

        class FakePoller:
            def __init__(self, client, episode_recorder, state_path, *, active_thread_hours: float) -> None:
                pass

            def poll_once(
                self,
                channel: str,
                *,
                backfill_hours: float | None,
                force_backfill: bool,
                history_limit: int,
                reply_limit: int,
                extract_memory: bool,
            ) -> SlackPollResult:
                poll_calls.append(extract_memory)
                return SlackPollResult(
                    channel=channel,
                    checked_threads=1,
                    ingested_threads=1,
                    latest_history_ts="1781798400.000000",
                    memory_extraction_enabled=extract_memory,
                    ingested_episode_ids=["episode_1"],
                    episode_records=[EpisodeRecordResult(episode_id="episode_1")],
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.SlackWebApiClient", return_value=object()):
                    with patch("tailwag_memory.cli.TailwagMemoryClient", FakeMemoryClient):
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
                                        "--skip-memory-extraction",
                                    ]
                                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(poll_calls, [False])
        output = json.loads(stdout.getvalue())
        self.assertFalse(output["memory_extraction_enabled"])
        self.assertEqual(output["episode_records"][0]["memory_results"], [])

    def test_slack_poll_passes_include_email_to_client(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            slack_bot_token="xoxb-test-token",
        )
        runner = FakeRunner(settings)
        client_calls = []

        class FakeMemoryClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

        class FakePoller:
            def __init__(self, client, episode_recorder, state_path, *, active_thread_hours: float) -> None:
                pass

            def poll_once(
                self,
                channel: str,
                *,
                backfill_hours: float | None,
                force_backfill: bool,
                history_limit: int,
                reply_limit: int,
                extract_memory: bool,
            ) -> SlackPollResult:
                return SlackPollResult(channel=channel, checked_threads=0, ingested_threads=0, latest_history_ts=None)

        def fake_slack_client(token: str, *, include_email: bool = False):
            client_calls.append({"token": token, "include_email": include_email})
            return object()

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.SlackWebApiClient", fake_slack_client):
                    with patch("tailwag_memory.cli.TailwagMemoryClient", FakeMemoryClient):
                        with patch("tailwag_memory.cli.SlackMemoryPoller", FakePoller):
                            stdout = StringIO()
                            with redirect_stdout(stdout):
                                exit_code = main(["slack", "poll", "--channel", "C123", "--once", "--include-email"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(client_calls, [{"token": "xoxb-test-token", "include_email": True}])

    def test_person_context_prints_unified_context(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def person_context(
                self,
                person_id: str,
                limit: int = 10,
                semantic_scope: str | None = None,
                *,
                current_text: str | None = None,
                memory_limit: int = 12,
                recent_episode_limit: int = 5,
            ) -> str:
                calls.append(
                    {
                        "person_id": person_id,
                        "limit": limit,
                        "semantic_scope": semantic_scope,
                        "current_text": current_text,
                        "memory_limit": memory_limit,
                        "recent_episode_limit": recent_episode_limit,
                    }
                )
                return "[PERSON MEMORY]\nPreferences:\n- likes robot demos\n\nJamie recently asked about chargers."

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
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
                                "--current-text",
                                "robot demo",
                                "--memory-limit",
                                "4",
                                "--recent-episode-limit",
                                "2",
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            calls,
            [
                {
                    "person_id": "person_jamie",
                    "limit": 3,
                    "semantic_scope": None,
                    "current_text": "robot demo",
                    "memory_limit": 4,
                    "recent_episode_limit": 2,
                }
            ],
        )
        self.assertIn("[PERSON MEMORY]", stdout.getvalue())
        self.assertIn("Jamie recently asked about chargers.", stdout.getvalue())
        self.assertTrue(runner.closed)

    def test_seed_demo_uses_mock_embeddings(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=8,
        )
        runner = FakeRunner(settings)
        calls = []

        def fake_seed(runner_arg, embeddings) -> None:
            calls.append((runner_arg, embeddings.embed("demo")))

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.demo.seed_demo", fake_seed):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(["seed", "demo"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0][0], runner)
        self.assertEqual(len(calls[0][1]), 8)
        self.assertIn("Demo data seeded.", stdout.getvalue())

    def test_episode_create_help_mentions_memory_extraction(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["episode", "create", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--file", help_text)
        self.assertIn("--skip-memory-extraction", help_text)
        self.assertIn("OpenAI-backed memory", help_text)
        self.assertIn("extraction", help_text)

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

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def person_context(
                self,
                person_id: str,
                limit: int = 10,
                semantic_scope: str | None = None,
                **kwargs,
            ) -> str:
                calls.append({"person_id": person_id, "limit": limit, "semantic_scope": semantic_scope})
                return "Jamie recently asked about chargers."

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
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

    def test_memory_help_excludes_context_command(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["memory", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("extract", help_text)
        self.assertIn("consolidate", help_text)
        self.assertNotIn("context", help_text)

    def test_memory_consolidate_person_outputs_json(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def consolidate_memory(self, **kwargs):
                calls.append(kwargs)
                return MemoryConsolidationResult(
                    person_results=[
                        PersonMemoryConsolidationResult(
                            person_id="person_jamie",
                            created_memory_ids=["mem_1"],
                            superseded_memory_ids=["mem_old"],
                            candidate_episode_ids=["ep1", "ep2", "ep3", "ep4"],
                            provider_called=True,
                        )
                    ]
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(["memory", "consolidate", "--person-id", "person_jamie"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["person_id"], "person_jamie")
        self.assertFalse(calls[0]["all_people"])
        self.assertEqual(calls[0]["min_evidence_episodes"], 4)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["person_results"][0]["created_memory_ids"], ["mem_1"])
        self.assertEqual(output["person_results"][0]["superseded_memory_ids"], ["mem_old"])
        self.assertTrue(runner.closed)

    def test_memory_consolidate_all_outputs_json(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def consolidate_memory(self, **kwargs):
                calls.append(kwargs)
                return MemoryConsolidationResult(
                    person_results=[PersonMemoryConsolidationResult(person_id="person_jamie")]
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "memory",
                                "consolidate",
                                "--all",
                                "--person-limit",
                                "7",
                                "--min-evidence-episodes",
                                "5",
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertIsNone(calls[0]["person_id"])
        self.assertTrue(calls[0]["all_people"])
        self.assertEqual(calls[0]["person_limit"], 7)
        self.assertEqual(calls[0]["min_evidence_episodes"], 5)
        self.assertEqual(json.loads(stdout.getvalue())["person_results"][0]["person_id"], "person_jamie")

    def test_memory_consolidate_requires_one_target_before_runner(self) -> None:
        with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["memory", "consolidate"])

        self.assertEqual(raised.exception.code, 2)
        runner_class.assert_not_called()
        self.assertIn("one of the arguments --person-id --all is required", stderr.getvalue())

    def test_memory_consolidate_rejects_two_targets_before_runner(self) -> None:
        with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["memory", "consolidate", "--person-id", "person_jamie", "--all"])

        self.assertEqual(raised.exception.code, 2)
        runner_class.assert_not_called()
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_episode_create_extracts_memory_by_default(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                self.runner = runner_arg
                self.settings = settings_arg

            def record_episode(self, episode, *, extract_memory: bool = True):
                calls.append({"episode_id": episode.id, "extract_memory": extract_memory})
                return EpisodeRecordResult(
                    episode_id=episode.id,
                    memory_results=[PersonMemoryExtractionResult(person_id="person_jamie", created_memory_ids=["mem_1"])],
                )

        with tempfile.TemporaryDirectory() as tmp:
            path = self._episode_file(tmp)
            with patch("tailwag_memory.cli.load_settings", return_value=settings):
                with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                    with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
                        stdout = StringIO()
                        with redirect_stdout(stdout):
                            exit_code = main(["episode", "create", "--file", path])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [{"episode_id": "episode_1", "extract_memory": True}])
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["episode_id"], "episode_1")
        self.assertEqual(output["memory_results"][0]["created_memory_ids"], ["mem_1"])
        self.assertTrue(runner.closed)

    def test_episode_create_can_skip_memory_extraction(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def record_episode(self, episode, *, extract_memory: bool = True):
                calls.append(extract_memory)
                return EpisodeRecordResult(episode_id=episode.id)

        with tempfile.TemporaryDirectory() as tmp:
            path = self._episode_file(tmp)
            with patch("tailwag_memory.cli.load_settings", return_value=settings):
                with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                    with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
                        stdout = StringIO()
                        with redirect_stdout(stdout):
                            exit_code = main(["episode", "create", "--file", path, "--skip-memory-extraction"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [False])
        self.assertEqual(json.loads(stdout.getvalue())["memory_results"], [])

    def test_memory_extract_outputs_episode_memory_result(self) -> None:
        settings = Settings(
            neo4j_uri="bolt://example.test:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            embedding_dimension=64,
            openai_api_key="test-key",
        )
        runner = FakeRunner(settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def extract_memory_for_episode(self, episode_id: str, person_id: str | None = None):
                calls.append({"episode_id": episode_id, "person_id": person_id})
                return EpisodeMemoryExtractionResult(
                    episode_id=episode_id,
                    memory_results=[PersonMemoryExtractionResult(person_id=person_id or "person_jamie")],
                )

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.cli.TailwagMemoryClient", FakeClient):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "memory",
                                "extract",
                                "--episode-id",
                                "episode_1",
                                "--person-id",
                                "person_jamie",
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [{"episode_id": "episode_1", "person_id": "person_jamie"}])
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["episode_id"], "episode_1")
        self.assertEqual(output["memory_results"][0]["person_id"], "person_jamie")

    def test_memory_extract_missing_episode_id_exits_before_runner(self) -> None:
        with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
            stderr = StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["memory", "extract"])

        self.assertEqual(raised.exception.code, 2)
        runner_class.assert_not_called()
        self.assertIn("--episode-id", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
