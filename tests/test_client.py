from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from tests.helpers import RecordingQueryRunner, test_episode, test_settings
from tailwag_memory.client import TailwagMemoryClient
from tailwag_memory.config import Settings
from tailwag_memory.episode_normalization import normalize_robot_speaker_labels
from tailwag_memory.models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    EpisodeMemoryResult,
    MemoryConsolidationResult,
    MemoryItemResult,
    PersonInput,
    PersonMemoryConsolidationResult,
    PersonMemoryExtractionResult,
    PlaceInput,
)


def _settings() -> Settings:
    return test_settings()


def _episode() -> EpisodeInput:
    return test_episode()


class TailwagMemoryClientTest(unittest.TestCase):
    def test_upsert_person_delegates_without_initializing_embeddings(self) -> None:
        runner = RecordingQueryRunner()
        calls = []
        person = PersonInput(
            id="person_jamie",
            display_name="Jamie",
            email="jamie@example.com",
            consent_status="consented",
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
        runner = RecordingQueryRunner()
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
        runner = RecordingQueryRunner()
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
        runner = RecordingQueryRunner()
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

    def test_biometric_enrollment_uses_configured_models(self) -> None:
        runner = RecordingQueryRunner()
        client = TailwagMemoryClient(
            runner,
            test_settings(
                face_embedding_model="facenet-vggface2",
                voice_embedding_model="ecapa",
            ),
        )

        client.enroll_face_reference(
            person_id="person_jamie",
            embedding=[0.1] * 512,
        )
        face_query = runner.queries[-1]
        self.assertEqual(face_query.parameters["model"], "facenet-vggface2")

        client.enroll_voice_reference(
            person_id="person_jamie",
            embedding=[0.2] * 192,
        )
        voice_query = runner.queries[-1]
        self.assertEqual(voice_query.parameters["model"], "ecapa")

    def test_record_episode_ingests_and_extracts_memory_by_default(self) -> None:
        runner = RecordingQueryRunner()
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
                            addressed_memory_ids=["mem_followup_addressed"],
                            supported_memory_ids=["mem_followup_supported"],
                        )
                    ],
                )

        with patch("tailwag_memory.client.EpisodeIngestionService", FakeIngestion):
            with patch("tailwag_memory.client.EpisodeMemoryExtractionService", FakeExtraction):
                result = TailwagMemoryClient(runner, _settings()).record_episode(_episode())

        self.assertEqual(calls, [("ingest", "episode_1"), ("extract", "episode_1", False)])
        self.assertEqual(result.episode_id, "episode_1")
        self.assertEqual(result.memory_results[0].created_memory_ids, ["mem_1"])
        self.assertEqual(result.memory_results[0].addressed_memory_ids, ["mem_followup_addressed"])
        self.assertEqual(result.memory_results[0].supported_memory_ids, ["mem_followup_supported"])
        self.assertEqual(result.memory_errors, [])

    def test_record_episode_normalizes_robot_user_label_for_single_speaker(self) -> None:
        runner = RecordingQueryRunner()
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

    def test_robot_user_label_normalization_variants(self) -> None:
        cases = [
            (
                [PersonInput(id="person_jamie", role="speaker")],
                "User: I like robot demos.",
                "person_jamie: I like robot demos.",
            ),
            (
                [PersonInput(id="person_jamie", display_name="Jamie")],
                "User: I like robot demos.",
                "Jamie: I like robot demos.",
            ),
            (
                [PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
                "The word User: appears here.\n  User: This line is labeled.",
                "The word User: appears here.\n  Jamie: This line is labeled.",
            ),
        ]
        for participants, transcript, expected in cases:
            with self.subTest(expected=expected):
                episode = test_episode(
                    transcript=transcript,
                    building_code="ARGOS",
                    room_id="realtime",
                    participants=participants,
                )
                self.assertEqual(normalize_robot_speaker_labels(episode).transcript, expected)

        for participants in [
            [],
            [
                PersonInput(id="person_jamie", display_name="Jamie", role="speaker"),
                PersonInput(id="person_casey", display_name="Casey", role="speaker"),
            ],
        ]:
            episode = test_episode(
                transcript="User: I like robot demos.\nAssistant: Got it.",
                building_code="ARGOS",
                room_id="realtime",
                participants=participants,
            )
            self.assertIs(normalize_robot_speaker_labels(episode), episode)

    def test_record_episode_can_skip_memory_extraction(self) -> None:
        runner = RecordingQueryRunner()
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
        runner = RecordingQueryRunner()
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
            ) -> str:
                memory_calls.append((person_id, current_text, now, memory_limit))
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
                context = TailwagMemoryClient(RecordingQueryRunner(), _settings()).person_context(
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
        self.assertEqual(memory_calls, [("person_jamie", "robot demo", now, 4)])
        self.assertEqual(retrieval_calls, [("person_jamie", 3, "chargers")])

    def test_search_semantic_memory_returns_episode_and_memory_item_results(self) -> None:
        runner = RecordingQueryRunner()
        calls = []
        now = datetime(2026, 6, 18, tzinfo=timezone.utc)

        class FakeEmbeddingProvider:
            def embed(self, text: str) -> list[float]:
                calls.append(("embed", text))
                return [0.1, 0.2]

        class FakeEpisodeRetrieval:
            def __init__(self, runner_arg, embeddings) -> None:
                calls.append(("episode_init", runner_arg, embeddings))

            def hybrid_search_with_embedding(self, query, embedding):
                calls.append(("episode_search", query, embedding))
                return [
                    EpisodeMemoryResult(
                        episode_id="episode_1",
                        transcript="Jamie: Robot demos are scheduled.",
                        score=0.7,
                        start_time="2026-06-01T10:00:00Z",
                        end_time="2026-06-01T10:05:00Z",
                        building_code="BOS",
                        room_id="lab",
                    )
                ]

        class FakeMemoryItemService:
            def __init__(self, runner_arg, embeddings) -> None:
                calls.append(("memory_init", runner_arg, embeddings))

            def vector_search_by_embedding(self, **kwargs):
                calls.append(("memory_search", kwargs))
                return [
                    MemoryItemResult(
                        memory_id="memory_1",
                        person_id="person_jamie",
                        kind="preference",
                        key="demos",
                        summary="Likes robot demos.",
                        source="extracted",
                        source_ref="episode_1",
                        observed_at="2026-06-01T10:00:00Z",
                        score=0.9,
                    )
                ]

        client = TailwagMemoryClient(runner, _settings())
        embedding_provider = FakeEmbeddingProvider()
        with patch.object(client, "_embeddings", return_value=embedding_provider):
            with patch("tailwag_memory.client.EpisodeRetrievalService", FakeEpisodeRetrieval):
                with patch("tailwag_memory.client.MemoryItemService", FakeMemoryItemService):
                    result = client.search_semantic_memory(
                        text=" robot demos ",
                        person_id=" person_jamie ",
                        building_code=" BOS ",
                        limit=3,
                        now=now,
                    )

        self.assertEqual(calls[0], ("embed", "robot demos"))
        self.assertEqual(calls[1], ("episode_init", runner, embedding_provider))
        self.assertEqual(calls[2][0], "episode_search")
        self.assertEqual(calls[2][1].text, "robot demos")
        self.assertEqual(calls[2][1].person_id, "person_jamie")
        self.assertEqual(calls[2][1].building_code, "BOS")
        self.assertIsNone(calls[2][1].room_id)
        self.assertEqual(calls[2][1].limit, 3)
        self.assertEqual(calls[2][2], [0.1, 0.2])
        self.assertEqual(calls[3], ("memory_init", runner, embedding_provider))
        self.assertEqual(
            calls[4],
            (
                "memory_search",
                {
                    "person_id": "person_jamie",
                    "embedding": [0.1, 0.2],
                    "limit": 3,
                    "now": now,
                },
            ),
        )
        self.assertEqual(
            result,
            {
                "episodes": [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Robot demos are scheduled.",
                        "score": 0.7,
                        "start_time": "2026-06-01T10:00:00Z",
                        "end_time": "2026-06-01T10:05:00Z",
                        "building_code": "BOS",
                        "room_id": "lab",
                    }
                ],
                "memory_items": [
                    {
                        "memory_id": "memory_1",
                        "person_id": "person_jamie",
                        "kind": "preference",
                        "key": "demos",
                        "summary": "Likes robot demos.",
                        "source": "extracted",
                        "source_ref": "episode_1",
                        "status": "active",
                        "observed_at": "2026-06-01T10:00:00Z",
                        "created_at": "",
                        "updated_at": "",
                        "due_at": "",
                        "expires_at": "",
                        "metadata": {},
                        "score": 0.9,
                    }
                ],
            },
        )

    def test_search_semantic_memory_skips_empty_requests_without_embeddings(self) -> None:
        client = TailwagMemoryClient(RecordingQueryRunner(), _settings())

        empty_result = {"episodes": [], "memory_items": []}
        with patch.object(client, "_embeddings", side_effect=AssertionError("embeddings should not be initialized")):
            self.assertEqual(client.search_semantic_memory(text=" ", person_id="person_jamie"), empty_result)
            self.assertEqual(client.search_semantic_memory(text="demos", person_id=" "), empty_result)

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
            client = TailwagMemoryClient(RecordingQueryRunner(), _settings())
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
            TailwagMemoryClient(RecordingQueryRunner(), _settings()).consolidate_memory()

    def test_context_manager_closes_runner(self) -> None:
        runner = RecordingQueryRunner()

        with TailwagMemoryClient(runner, _settings()):
            pass

        self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
