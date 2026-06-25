from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tailwag_memory.client import TailwagMemoryClient
from tailwag_memory.config import Settings
from tailwag_memory.episode_normalization import normalize_robot_speaker_labels
from tailwag_memory.models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    MemoryConsolidationResult,
    PersonInput,
    PersonMemoryConsolidationResult,
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
        transcript="Jamie: I like robot demos.",
        retention_class="standard",
        place=PlaceInput(building_code="MAIN", room_id="101"),
        participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
    )


class TailwagMemoryClientTest(unittest.TestCase):
    def test_upsert_person_delegates_without_initializing_embeddings(self) -> None:
        runner = FakeRunner()
        calls = []
        person = PersonInput(
            id="person_jamie",
            display_name="Jamie",
            email="jamie@example.com",
            consent_status="consented",
            face_embedding=[0.1] * 8,
        )

        class FakePersonIngestion:
            def __init__(self, runner_arg) -> None:
                self.runner_arg = runner_arg

            def upsert(self, person_arg: PersonInput) -> str:
                calls.append(("upsert", self.runner_arg, person_arg))
                return person_arg.id

        client = TailwagMemoryClient(runner, _settings())
        with patch.object(client, "_embeddings", side_effect=AssertionError("embeddings should not be initialized")):
            with patch("tailwag_memory.client.PersonIngestionService", FakePersonIngestion):
                result = client.upsert_person(person)

        self.assertEqual(result, "person_jamie")
        self.assertEqual(calls, [("upsert", runner, person)])

    def test_archive_person_delegates_without_initializing_embeddings(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakePersonIngestion:
            def __init__(self, runner_arg) -> None:
                self.runner_arg = runner_arg

            def archive(self, person_id: str) -> bool:
                calls.append(("archive", self.runner_arg, person_id))
                return True

        client = TailwagMemoryClient(runner, _settings())
        with patch.object(client, "_embeddings", side_effect=AssertionError("embeddings should not be initialized")):
            with patch("tailwag_memory.client.PersonIngestionService", FakePersonIngestion):
                result = client.archive_person("person_jamie")

        self.assertTrue(result)
        self.assertEqual(calls, [("archive", runner, "person_jamie")])

    def test_rekey_person_by_email_delegates_without_initializing_embeddings(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakePersonIngestion:
            def __init__(self, runner_arg) -> None:
                self.runner_arg = runner_arg

            def rekey_by_email(self, email: str, new_person_id: str) -> bool:
                calls.append(("rekey", self.runner_arg, email, new_person_id))
                return True

        client = TailwagMemoryClient(runner, _settings())
        with patch.object(client, "_embeddings", side_effect=AssertionError("embeddings should not be initialized")):
            with patch("tailwag_memory.client.PersonIngestionService", FakePersonIngestion):
                result = client.rekey_person_by_email("jamie@example.com", "person_argos_jamie")

        self.assertTrue(result)
        self.assertEqual(calls, [("rekey", runner, "jamie@example.com", "person_argos_jamie")])

    def test_canonical_person_id_by_email_delegates_without_initializing_embeddings(self) -> None:
        runner = FakeRunner()
        calls = []

        class FakePersonIngestion:
            def __init__(self, runner_arg) -> None:
                self.runner_arg = runner_arg

            def canonical_id_by_email(self, email: str) -> str | None:
                calls.append(("canonical", self.runner_arg, email))
                return "person_jamie"

        client = TailwagMemoryClient(runner, _settings())
        with patch.object(client, "_embeddings", side_effect=AssertionError("embeddings should not be initialized")):
            with patch("tailwag_memory.client.PersonIngestionService", FakePersonIngestion):
                result = client.canonical_person_id_by_email("jamie@example.com")

        self.assertEqual(result, "person_jamie")
        self.assertEqual(calls, [("canonical", runner, "jamie@example.com")])

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

    def test_record_episode_normalizes_robot_user_label_for_single_speaker(self) -> None:
        runner = FakeRunner()
        calls = []
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            transcript="User: I like robot demos.\nAssistant: I'll remember that.\nUser: Thanks.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
        )

        class FakeIngestion:
            def __init__(self, runner_arg, embeddings) -> None:
                pass

            def ingest(self, episode_arg: EpisodeInput) -> str:
                calls.append(("ingest", episode_arg))
                return episode_arg.id

        class FakeExtraction:
            def __init__(self, runner_arg, embeddings, provider) -> None:
                pass

            def extract_for_episode(self, episode_arg: EpisodeInput, *, speaker_only: bool):
                calls.append(("extract", episode_arg, speaker_only))
                return EpisodeMemoryExtractionResult(episode_id=episode_arg.id)

        with patch("tailwag_memory.client.EpisodeIngestionService", FakeIngestion):
            with patch("tailwag_memory.client.EpisodeMemoryExtractionService", FakeExtraction):
                TailwagMemoryClient(runner, _settings()).record_episode(episode)

        ingested = calls[0][1]
        extracted = calls[1][1]
        self.assertEqual(ingested.transcript, "Jamie: I like robot demos.\nAssistant: I'll remember that.\nJamie: Thanks.")
        self.assertIs(extracted, ingested)
        self.assertEqual(calls[1][2], False)

    def test_robot_user_label_uses_person_id_when_display_name_is_missing(self) -> None:
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            transcript="User: I like robot demos.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[PersonInput(id="person_jamie", role="speaker")],
        )

        normalized = normalize_robot_speaker_labels(episode)

        self.assertEqual(normalized.transcript, "person_jamie: I like robot demos.")

    def test_robot_user_label_without_speaker_role_uses_single_participant(self) -> None:
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            transcript="User: I like robot demos.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[PersonInput(id="person_jamie", display_name="Jamie")],
        )

        normalized = normalize_robot_speaker_labels(episode)

        self.assertEqual(normalized.transcript, "Jamie: I like robot demos.")

    def test_robot_user_label_is_not_changed_for_ambiguous_or_unlinked_episodes(self) -> None:
        base = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            transcript="User: I like robot demos.\nAssistant: Got it.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[],
        )
        multi_speaker = EpisodeInput(
            id=base.id,
            episode_type=base.episode_type,
            start_time=base.start_time,
            end_time=base.end_time,
            transcript=base.transcript,
            retention_class=base.retention_class,
            place=base.place,
            participants=[
                PersonInput(id="person_jamie", display_name="Jamie", role="speaker"),
                PersonInput(id="person_casey", display_name="Casey", role="speaker"),
            ],
        )

        self.assertIs(normalize_robot_speaker_labels(base), base)
        self.assertIs(normalize_robot_speaker_labels(multi_speaker), multi_speaker)

    def test_robot_user_label_replacement_only_matches_line_leading_labels(self) -> None:
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            transcript="The word User: appears here.\n  User: This line is labeled.",
            retention_class="standard",
            place=PlaceInput(building_code="ARGOS", room_id="realtime"),
            participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
        )

        normalized = normalize_robot_speaker_labels(episode)

        self.assertEqual(normalized.transcript, "The word User: appears here.\n  Jamie: This line is labeled.")

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

    def test_person_context_returns_durable_memory_without_redundant_retrieved_context(self) -> None:
        memory_calls = []
        retrieval_calls = []

        class FakeMemoryContext:
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
                memory_calls.append((person_id, current_text, now, memory_limit, recent_episode_limit))
                return "[PERSON MEMORY]\nPreferences:\n- likes robot demos"

        class FakeRetrieval:
            def __init__(self, runner_arg, embeddings) -> None:
                pass

            def markdown_for_person(
                self,
                person_id: str,
                limit: int = 10,
                semantic_scope: str | None = None,
            ) -> str:
                retrieval_calls.append((person_id, limit, semantic_scope))
                return ""

        now = datetime(2026, 6, 18, tzinfo=timezone.utc)
        with patch("tailwag_memory.client.PersonMemoryContextService", FakeMemoryContext):
            with patch("tailwag_memory.client.PersonContextRetrievalService", FakeRetrieval):
                context = TailwagMemoryClient(FakeRunner(), _settings()).person_context(
                    "person_jamie",
                    limit=3,
                    semantic_scope="chargers",
                    current_text="robot demo",
                    now=now,
                    memory_limit=4,
                    recent_episode_limit=2,
                )

        self.assertEqual(
            context,
            "[PERSON MEMORY]\nPreferences:\n- likes robot demos",
        )
        self.assertEqual(memory_calls, [("person_jamie", "robot demo", now, 4, 2)])
        self.assertEqual(retrieval_calls, [("person_jamie", 3, "chargers")])

    def test_consolidate_memory_routes_single_person_and_all_people(self) -> None:
        calls = []

        class FakeConsolidationService:
            def __init__(self, runner_arg, embeddings, provider) -> None:
                pass

            def consolidate_person(self, person_id: str, **kwargs):
                calls.append(("person", person_id, kwargs))
                return PersonMemoryConsolidationResult(person_id=person_id, created_memory_ids=["mem_1"])

            def consolidate_all(self, **kwargs):
                calls.append(("all", kwargs))
                return MemoryConsolidationResult(
                    person_results=[PersonMemoryConsolidationResult(person_id="person_jamie")]
                )

        with patch("tailwag_memory.client.MemoryConsolidationService", FakeConsolidationService):
            client = TailwagMemoryClient(FakeRunner(), _settings())
            single = client.consolidate_memory(person_id="person_jamie", min_evidence_episodes=4)
            all_people = client.consolidate_memory(all_people=True, person_limit=7, min_evidence_episodes=5)

        self.assertEqual(single.person_results[0].created_memory_ids, ["mem_1"])
        self.assertEqual(all_people.person_results[0].person_id, "person_jamie")
        self.assertEqual(calls[0][0], "person")
        self.assertEqual(calls[0][1], "person_jamie")
        self.assertEqual(calls[0][2]["min_evidence_episodes"], 4)
        self.assertEqual(calls[1], ("all", {"person_limit": 7, "min_evidence_episodes": 5, "seed_limit": 25, "neighbor_limit": 12, "cluster_limit": 8, "episode_text_limit": 1200}))

    def test_consolidate_memory_requires_person_or_all_people(self) -> None:
        with self.assertRaisesRegex(ValueError, "person_id"):
            TailwagMemoryClient(FakeRunner(), _settings()).consolidate_memory()

    def test_context_manager_closes_runner(self) -> None:
        runner = FakeRunner()

        with TailwagMemoryClient(runner, _settings()):
            pass

        self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
