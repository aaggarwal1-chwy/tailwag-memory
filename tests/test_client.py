from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tailwag_memory.client import TailwagMemoryClient
from tailwag_memory.config import Settings
from tailwag_memory.models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    PersonInput,
    PersonMemoryExtractionResult,
    PlaceInput,
)


class FakeRunner:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _settings() -> Settings:
    return Settings(
        neo4j_uri="bolt://example.test:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        embedding_dimension=8,
        openai_api_key="test-key",
    )


def _episode() -> EpisodeInput:
    return EpisodeInput(
        id="episode_1",
        episode_type="conversation",
        start_time="2026-06-18T10:00:00+00:00",
        end_time=None,
        summary="Jamie likes robot demos.",
        transcript="Jamie: I like robot demos.",
        retention_class="standard",
        place=PlaceInput(building_code="MAIN", room_id="101"),
        participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
    )


class TailwagMemoryClientTest(unittest.TestCase):
    def test_record_episode_ingests_and_extracts_memory_by_default(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakeIngestion:
            def __init__(self, runner_arg, embeddings) -> None:
                self.runner_arg = runner_arg
                self.embeddings = embeddings

            def ingest(self, episode: EpisodeInput) -> str:
                calls.append(("ingest", episode.id))
                return episode.id

        class FakeExtraction:
            def __init__(self, runner_arg, embeddings, provider) -> None:
                self.runner_arg = runner_arg
                self.embeddings = embeddings
                self.provider = provider

            def extract_for_episode(self, episode: EpisodeInput, *, speaker_only: bool):
                calls.append(("extract", episode.id, speaker_only))
                return EpisodeMemoryExtractionResult(
                    episode_id=episode.id,
                    memory_results=[
                        PersonMemoryExtractionResult(
                            person_id="person_jamie",
                            update_requested=True,
                            created_memory_ids=["mem_1"],
                        )
                    ],
                )

        with patch("tailwag_memory.client.EpisodeIngestionService", FakeIngestion):
            with patch("tailwag_memory.client.EpisodeMemoryExtractionService", FakeExtraction):
                result = TailwagMemoryClient(runner, _settings()).record_episode(_episode())

        self.assertEqual(calls, [("ingest", "episode_1"), ("extract", "episode_1", False)])
        self.assertEqual(result.episode_id, "episode_1")
        self.assertEqual(result.memory_results[0].created_memory_ids, ["mem_1"])
        self.assertEqual(result.memory_errors, [])

    def test_record_episode_can_skip_memory_extraction(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakeIngestion:
            def __init__(self, runner_arg, embeddings) -> None:
                pass

            def ingest(self, episode: EpisodeInput) -> str:
                calls.append(("ingest", episode.id))
                return episode.id

        with patch("tailwag_memory.client.EpisodeIngestionService", FakeIngestion):
            result = TailwagMemoryClient(runner, _settings()).record_episode(_episode(), extract_memory=False)

        self.assertEqual(calls, [("ingest", "episode_1")])
        self.assertEqual(result.memory_results, [])
        self.assertEqual(result.memory_errors, [])

    def test_extract_memory_for_episode_uses_stored_episode_path(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakeExtraction:
            def __init__(self, runner_arg, embeddings, provider) -> None:
                pass

            def extract_for_stored_episode(self, episode_id: str, *, person_id: str | None, speaker_only: bool):
                calls.append({"episode_id": episode_id, "person_id": person_id, "speaker_only": speaker_only})
                return EpisodeMemoryExtractionResult(episode_id=episode_id)

        with patch("tailwag_memory.client.EpisodeMemoryExtractionService", FakeExtraction):
            result = TailwagMemoryClient(runner, _settings()).extract_memory_for_episode(
                "episode_1",
                person_id="person_jamie",
            )

        self.assertEqual(result.episode_id, "episode_1")
        self.assertEqual(calls, [{"episode_id": "episode_1", "person_id": "person_jamie", "speaker_only": True}])

    def test_person_memory_context_returns_markdown_context(self) -> None:
        calls = []

        class FakeMarkdownContext:
            def __init__(self, runner_arg, embeddings) -> None:
                pass

            def markdown_for_person(
                self,
                person_id: str,
                *,
                current_text: str | None = None,
                now=None,
                memory_limit: int = 12,
                recent_episode_limit: int = 5,
            ) -> str:
                calls.append((person_id, current_text, now, memory_limit, recent_episode_limit))
                return f"{person_id}: {current_text}"

        now = datetime(2026, 6, 18, tzinfo=timezone.utc)
        with patch("tailwag_memory.client.PersonMarkdownContextService", FakeMarkdownContext):
            context = TailwagMemoryClient(FakeRunner(), _settings()).person_memory_context(
                "person_jamie",
                current_text="robot demo",
                now=now,
                memory_limit=4,
                recent_episode_limit=2,
            )

        self.assertEqual(context, "person_jamie: robot demo")
        self.assertEqual(calls, [("person_jamie", "robot demo", now, 4, 2)])

    def test_context_manager_closes_runner(self) -> None:
        runner = FakeRunner()

        with TailwagMemoryClient(runner, _settings()):
            pass

        self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
