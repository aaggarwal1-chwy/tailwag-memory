from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.models import SearchQuery
from tailwag_memory.retrieval import EpisodeRetrievalService, PersonRecognitionService
import unittest


class EpisodeRetrievalServiceTest(unittest.TestCase):
    def test_vector_search_uses_summary_index_by_default(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "summary": "Jamie asked about chargers.",
                        "transcript": "Jamie: Any chargers?",
                        "score": 0.91,
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.vector_search("chargers")

        self.assertEqual(results[0].episode_id, "episode_1")
        self.assertEqual(results[0].score, 0.91)
        self.assertEqual(runner.queries[0].parameters["index_name"], "episode_summary_embedding")

    def test_vector_search_can_use_transcript_index(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        service.vector_search("chargers", target="transcript")

        self.assertEqual(runner.queries[0].parameters["index_name"], "episode_transcript_embedding")

    def test_hybrid_search_includes_graph_filters(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        service.hybrid_search(
            SearchQuery(
                text="chargers",
                person_id="person_jamie",
                building_code="MAIN",
                room_id="101",
                limit=5,
            )
        )

        params = runner.queries[0].parameters
        self.assertEqual(params["person_id"], "person_jamie")
        self.assertEqual(params["building_code"], "MAIN")
        self.assertEqual(params["room_id"], "101")
        self.assertEqual(params["limit"], 5)

    def test_retrieval_rejects_unknown_vector_target(self) -> None:
        service = EpisodeRetrievalService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "summary"):
            service.vector_search("chargers", target="semantic_fact")


class PersonRecognitionServiceTest(unittest.TestCase):
    def test_face_search_uses_person_face_index(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "consent_status": "consented",
                        "last_seen": "2026-06-15T10:00:00+00:00",
                        "score": 0.98,
                    }
                ]
            ]
        )
        service = PersonRecognitionService(runner)

        results = service.by_face_embedding([0.1] * 8, limit=3)

        self.assertEqual(results[0].person_id, "person_jamie")
        self.assertEqual(results[0].score, 0.98)
        self.assertEqual(runner.queries[0].parameters["index_name"], "person_face_embedding")
        self.assertEqual(runner.queries[0].parameters["limit"], 3)

    def test_audio_search_uses_person_audio_index(self) -> None:
        runner = RecordingQueryRunner()
        service = PersonRecognitionService(runner)

        service.by_audio_embedding([0.2] * 8, limit=4)

        self.assertEqual(runner.queries[0].parameters["index_name"], "person_audio_embedding")
        self.assertEqual(runner.queries[0].parameters["limit"], 4)


if __name__ == "__main__":
    unittest.main()
