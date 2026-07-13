from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import RecordingQueryRunner, test_settings
from tailwag_memory.cli import main
from tailwag_memory.inspect import AffectScore
from tailwag_memory.inspect.html_utils import INSPECT_CSS_FILENAME, INSPECT_JS_FILENAME, inspect_asset_text
from tailwag_memory.models import (
    EpisodeMemoryExtractionResult,
    EpisodeRecordResult,
    MemoryConsolidationResult,
    PersonMemoryConsolidationResult,
    PersonMemoryExtractionResult,
)
from tailwag_memory.slack_ingestion import SlackPollResult


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
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(["db", "wipe", "--yes"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(runner.queries[0].query, "MATCH (n) DETACH DELETE n")
        self.assertEqual(runner.queries[0].parameters, {})
        self.assertTrue(runner.closed)
        self.assertIn("Neo4j data wiped.", stdout.getvalue())

    def test_slack_poll_missing_token_exits_before_db_runner(self) -> None:
        settings = test_settings(embedding_dimension=64, slack_bot_token=None)

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
        settings = test_settings(embedding_dimension=64, slack_bot_token="xoxb-test-token")
        runner = RecordingQueryRunner(settings=settings)
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
        settings = test_settings(embedding_dimension=64, slack_bot_token="xoxb-test-token")
        runner = RecordingQueryRunner(settings=settings)
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
        settings = test_settings(embedding_dimension=64, slack_bot_token="xoxb-test-token")
        runner = RecordingQueryRunner(settings=settings)
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

    def test_inspect_affect_missing_model_dirs_exits_before_db_runner(self) -> None:
        settings = test_settings(embedding_dimension=64)

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner") as runner_class:
                stderr = StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        main(["inspect", "affect", "--format", "json"])

        self.assertEqual(raised.exception.code, 2)
        runner_class.assert_not_called()
        self.assertIn("--fold1-model or TAILWAG_AFFECT_FOLD1_MODEL is required", stderr.getvalue())

    def test_inspect_affect_json_scores_person_episode_points(self) -> None:
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)
        runner.results = [
            [
                {
                    "episode_id": "episode_1",
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "speaker_labels": ["person_jamie", "Jamie", "Assistant"],
                    "transcript": "Jamie: I felt good about the demo. Assistant: Nice.",
                    "start_time": "2026-06-16T14:00:00+00:00",
                    "building_code": "MAIN",
                    "room_id": "101",
                    "role": "speaker",
                    "source": "caller",
                    "memory_item_count": 1,
                    "related_memory_items": [
                        {
                            "memory_id": "mem_demo",
                            "kind": "preference",
                            "status": "active",
                            "summary": "Jamie likes concise demos.",
                        }
                    ],
                }
            ]
        ]

        class FakeProvider:
            def score(self, text: str) -> AffectScore:
                self.text = text
                return AffectScore(valence=0.25, arousal=0.75, metadata={"fake": True})

        with tempfile.TemporaryDirectory() as tmp:
            fold1 = Path(tmp) / "fold1"
            fold2 = Path(tmp) / "fold2"
            fold1.mkdir()
            fold2.mkdir()
            with patch("tailwag_memory.cli.load_settings", return_value=settings):
                with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                    with patch(
                        "tailwag_memory.inspect.cli_handlers.FoldEnsembleAffectProvider.from_model_dirs",
                        return_value=FakeProvider(),
                    ) as provider_factory:
                        stdout = StringIO()
                        with redirect_stdout(stdout):
                            exit_code = main(
                                [
                                    "inspect",
                                    "affect",
                                    "--format",
                                    "json",
                                    "--output",
                                    "-",
                                    "--person-id",
                                    "person_jamie",
                                    "--limit",
                                    "5",
                                    "--fold1-model",
                                    str(fold1),
                                    "--fold2-model",
                                    str(fold2),
                                ]
                            )

            fold1_text = str(fold1)
            fold2_text = str(fold2)

        self.assertEqual(exit_code, 0)
        self.assertTrue(runner.closed)
        provider_factory.assert_called_once_with(fold1_text, fold2_text)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 5})
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["title"], "Affect Scatter")
        self.assertEqual(output["filters"], {"limit": 5, "person_id": "person_jamie"})
        self.assertEqual(output["metadata"]["storage"], "on_demand")
        self.assertEqual(output["records"][0]["valence"], 0.25)
        self.assertEqual(output["records"][0]["arousal"], 0.75)
        self.assertEqual(output["records"][0]["transcript"]["text"], "I felt good about the demo.")
        self.assertTrue(output["records"][0]["transcript"]["has_memory_items"])
        self.assertEqual(output["records"][0]["transcript"]["memory_item_count"], 1)
        self.assertEqual(
            output["records"][0]["transcript"]["related_memory_items"][0]["summary"],
            "Jamie likes concise demos.",
        )

    def test_inspect_followup_validity_json_uses_inspect_report(self) -> None:
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)
        runner.results = [
            [
                {
                    "memory_id": "mem_followup",
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "summary": "Ask Jamie about the demo.",
                    "status": "active",
                    "observed_at": "2026-07-01T10:00:00+00:00",
                    "due_at": "2026-07-08T10:00:00+00:00",
                    "expires_at": "2026-07-15T10:00:00+00:00",
                    "addressed_count": 0,
                    "superseded_count": 0,
                }
            ]
        ]

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        ["inspect", "followup-validity", "--format", "json", "--output", "-", "--limit", "5"]
                    )

        self.assertEqual(exit_code, 0)
        self.assertTrue(runner.closed)
        self.assertEqual(runner.queries[0].parameters, {"limit": 5})
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["title"], "Follow-Up Validity")
        self.assertEqual(output["filters"], {"limit": 5})
        self.assertEqual(output["metadata"]["utility"], "inspect followup-validity")
        self.assertEqual(output["records"][0]["validity_bucket"], "4_to_7_days")
        self.assertIn("WHERE memory.kind = 'followup'", runner.queries[0].query)

    def test_inspect_person_timeline_json_uses_inspect_report(self) -> None:
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)
        runner.results = [
            [
                {
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "item_id": "episode_1",
                    "item_type": "episode",
                    "episode_id": "episode_1",
                    "event_id": None,
                    "text": "Jamie: I filed the update.",
                    "transcript": "Jamie: I filed the update.",
                    "speaker_labels": ["Jamie"],
                    "start_time": "2026-07-07T14:00:00+00:00",
                    "end_time": None,
                    "building_code": "MAIN",
                    "room_id": "101",
                    "role": "speaker",
                    "source": "caller",
                    "memory_item_count": 2,
                }
            ],
            [],
        ]

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "inspect",
                            "person-timeline",
                            "--format",
                            "json",
                            "--output",
                            "-",
                            "--person-id",
                            "person_jamie",
                            "--limit",
                            "5",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertTrue(runner.closed)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 5})
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 5})
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["title"], "Person Timeline")
        self.assertEqual(output["filters"], {"limit": 5, "person_id": "person_jamie"})
        self.assertEqual(output["metadata"]["utility"], "inspect person-timeline")
        self.assertEqual(output["metadata"]["storage"], "read_only")
        self.assertEqual(output["records"][0]["episode_id"], "episode_1")
        self.assertEqual(output["records"][0]["text"], "I filed the update.")
        self.assertEqual(output["records"][0]["transcript_snippets"][0]["speaker"], "Jamie")
        self.assertTrue(output["records"][0]["has_memory_items"])
        self.assertEqual(output["records"][0]["memory_item_count"], 2)

    def test_inspect_memory_items_json_uses_inspect_report(self) -> None:
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)
        runner.results = [
            [
                {
                    "memory_id": "mem_followup",
                    "person_id": "person_jamie",
                    "display_name": "Jamie",
                    "kind": "followup",
                    "key": "demo",
                    "summary": "Ask Jamie about the demo.",
                    "source": "extractor",
                    "source_ref": "episode_1",
                    "status": "active",
                    "observed_at": "2026-07-01T10:00:00+00:00",
                    "due_at": "2026-07-02T10:00:00+00:00",
                    "expires_at": "2099-07-09T10:00:00+00:00",
                    "metadata_json": '{"topic": "demo"}',
                    "supported_episode_ids": ["episode_1"],
                    "addressed_by": [],
                    "superseded_by_memory_ids": [],
                    "supersedes_memory_ids": [],
                }
            ],
            [
                {
                    "episode_count": 4,
                    "memory_episode_count": 2,
                    "memory_count": 1,
                }
            ]
        ]

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)

        with patch("tailwag_memory.cli.load_settings", return_value=settings):
            with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                with patch("tailwag_memory.inspect.memory_items.datetime", FixedDateTime):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "inspect",
                                "memory-items",
                                "--format",
                                "json",
                                "--output",
                                "-",
                                "--person-id",
                                "person_jamie",
                                "--limit",
                                "5",
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(runner.closed)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 5})
        self.assertEqual(runner.queries[1].parameters, {})
        for recorded_query in runner.queries:
            upper_query = recorded_query.query.upper()
            for write_keyword in [" CREATE ", " MERGE ", " SET ", " DELETE ", " REMOVE "]:
                self.assertNotIn(write_keyword, upper_query)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["title"], "Memory Items")
        self.assertEqual(output["filters"], {"limit": 5, "person_id": "person_jamie"})
        self.assertEqual(output["metadata"]["utility"], "inspect memory-items")
        self.assertEqual(output["metadata"]["storage"], "read_only")
        self.assertEqual(output["metadata"]["distributions"]["kind"], {"followup": 1})
        self.assertEqual(output["metadata"]["episode_counts"]["Episodes With Memories"], 2)
        self.assertEqual(output["metadata"]["overview_links"][0], {"count": 2, "source": "All Episodes", "target": "Episodes With Memories"})
        self.assertEqual(output["records"][0]["memory_id"], "mem_followup")
        self.assertEqual(output["records"][0]["supported_episode_ids"], ["episode_1"])
        self.assertEqual(output["records"][0]["followup_state"], "visible_now")

    def test_inspect_html_output_writes_packaged_assets(self) -> None:
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(
            settings=settings,
            results=[
                [],
                [{"episode_count": 0, "memory_episode_count": 0, "memory_count": 0}],
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "tailwag-memory-items.html"
            with patch("tailwag_memory.cli.load_settings", return_value=settings):
                with patch("tailwag_memory.cli.Neo4jQueryRunner", return_value=runner):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(["inspect", "memory-items", "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertEqual((Path(tmp) / INSPECT_CSS_FILENAME).read_text(), inspect_asset_text(INSPECT_CSS_FILENAME))
            self.assertEqual((Path(tmp) / INSPECT_JS_FILENAME).read_text(), inspect_asset_text(INSPECT_JS_FILENAME))

    def test_person_context_prints_unified_context(self) -> None:
        settings = test_settings(embedding_dimension=64, openai_api_key="test-key")
        runner = RecordingQueryRunner(settings=settings)
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

    def test_memory_consolidate_person_outputs_json(self) -> None:
        settings = test_settings(embedding_dimension=64, openai_api_key="test-key")
        runner = RecordingQueryRunner(settings=settings)
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
        settings = test_settings(embedding_dimension=64, openai_api_key="test-key")
        runner = RecordingQueryRunner(settings=settings)
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

    def test_episode_create_extracts_memory_by_default(self) -> None:
        settings = test_settings(embedding_dimension=64, openai_api_key="test-key")
        runner = RecordingQueryRunner(settings=settings)
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
        settings = test_settings(embedding_dimension=64)
        runner = RecordingQueryRunner(settings=settings)
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
        settings = test_settings(embedding_dimension=64, openai_api_key="test-key")
        runner = RecordingQueryRunner(settings=settings)
        calls = []

        class FakeClient:
            def __init__(self, runner_arg, settings_arg) -> None:
                pass

            def extract_memory_for_episode(self, episode_id: str, person_id: str | None = None):
                calls.append({"episode_id": episode_id, "person_id": person_id})
                return EpisodeMemoryExtractionResult(
                    episode_id=episode_id,
                    memory_results=[
                        PersonMemoryExtractionResult(
                            person_id=person_id or "person_jamie",
                            addressed_memory_ids=["mem_followup_addressed"],
                            supported_memory_ids=["mem_followup_supported"],
                        )
                    ],
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
        self.assertEqual(output["memory_results"][0]["addressed_memory_ids"], ["mem_followup_addressed"])
        self.assertEqual(output["memory_results"][0]["supported_memory_ids"], ["mem_followup_supported"])


if __name__ == "__main__":
    unittest.main()
