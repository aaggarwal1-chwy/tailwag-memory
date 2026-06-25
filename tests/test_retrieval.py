from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.models import SearchQuery
from tailwag_memory.retrieval import (
    EpisodeRetrievalService,
    EventRetrievalService,
    PersonContextRetrievalService,
    PersonRecognitionService,
    _vector_search_clause,
    recent_episode_rows_for_person,
)
import unittest


class EpisodeRetrievalServiceTest(unittest.TestCase):
    def test_recent_episode_rows_for_person_centralizes_context_query_shape(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "transcript": "Jamie: Any chargers?",
                        "text": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ]
            ]
        )

        rows = recent_episode_rows_for_person(runner, "person_jamie", 3)

        self.assertEqual(rows[0]["episode_id"], "episode_1")
        self.assertEqual(rows[0]["item_type"], "episode")
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 3})
        self.assertIn("e.id AS episode_id", runner.queries[0].query)
        self.assertIn("'episode' AS item_type", runner.queries[0].query)
        self.assertIn("person.id AS person_id", runner.queries[0].query)
        self.assertIn("person.display_name AS display_name", runner.queries[0].query)
        self.assertIn("speaker_labels AS speaker_labels", runner.queries[0].query)
        self.assertIn("e.transcript AS transcript", runner.queries[0].query)
        self.assertIn("PARTICIPATED_IN", runner.queries[0].query)

    def test_by_person_uses_recent_episode_helper_rows(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Any chargers?",
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.by_person("person_jamie", limit=2)

        self.assertEqual(results[0].episode_id, "episode_1")
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 2})
        self.assertIn("e.id AS episode_id", runner.queries[0].query)

    def test_vector_search_uses_transcript_index(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
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
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[0].query)
        self.assertIn("WHERE node:Episode", runner.queries[0].query)

    def test_search_clause_rejects_unknown_index_identifiers(self) -> None:
        # Vector index names are interpolated as string literals from a known allowlist.
        with self.assertRaisesRegex(ValueError, "unsupported vector index"):
            _vector_search_clause("episode_transcript_embedding) RETURN 1 //", "node", "limit")

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
        self.assertEqual(params["candidate_limit"], 25)
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[0].query)

    def test_hybrid_search_supports_one_sided_place_filters(self) -> None:
        runner = RecordingQueryRunner()
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        service.hybrid_search(SearchQuery(text="chargers", building_code="MAIN", limit=10))
        service.hybrid_search(SearchQuery(text="chargers", room_id="101", limit=10))

        building_query = runner.queries[0]
        room_query = runner.queries[1]
        self.assertEqual(building_query.parameters["building_code"], "MAIN")
        self.assertIsNone(building_query.parameters["room_id"])
        self.assertIsNone(room_query.parameters["building_code"])
        self.assertEqual(room_query.parameters["room_id"], "101")
        self.assertIn("$room_id IS NULL OR place.room_id = $room_id", building_query.query)
        self.assertIn("$building_code IS NULL OR place.building_code = $building_code", room_query.query)

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
        self.assertIn("db.index.vector.queryNodes('person_face_embedding'", runner.queries[0].query)
        self.assertEqual(runner.queries[0].parameters["limit"], 3)
        self.assertEqual(runner.queries[0].parameters["candidate_limit"], 25)
        self.assertIn("node.consent_status = 'consented'", runner.queries[0].query)
        self.assertIn("coalesce(node.status, 'active') <> 'archived'", runner.queries[0].query)
        self.assertIn("LIMIT $limit", runner.queries[0].query)

    def test_audio_search_uses_person_audio_index(self) -> None:
        runner = RecordingQueryRunner()
        service = PersonRecognitionService(runner)

        service.by_audio_embedding([0.2] * 8, limit=4)

        self.assertIn("db.index.vector.queryNodes('person_audio_embedding'", runner.queries[0].query)
        self.assertEqual(runner.queries[0].parameters["limit"], 4)
        self.assertIn("node.consent_status = 'consented'", runner.queries[0].query)
        self.assertIn("coalesce(node.status, 'active') <> 'archived'", runner.queries[0].query)


class EventRetrievalServiceTest(unittest.TestCase):
    def test_by_place_returns_events_for_place(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "event_id": "event_1",
                        "description": "Room 101 was reserved.",
                        "start_time": "2026-06-16T15:00:00+00:00",
                        "end_time": "2026-06-16T16:00:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                    }
                ]
            ]
        )
        service = EventRetrievalService(runner)

        results = service.by_place("MAIN", "101", limit=5)

        self.assertEqual(results[0].event_id, "event_1")
        self.assertEqual(results[0].building_code, "MAIN")
        self.assertEqual(results[0].room_id, "101")
        self.assertEqual(runner.queries[0].parameters["building_code"], "MAIN")
        self.assertEqual(runner.queries[0].parameters["room_id"], "101")
        self.assertEqual(runner.queries[0].parameters["limit"], 5)


class PersonContextRetrievalServiceTest(unittest.TestCase):
    def test_markdown_for_person_returns_unknown_person_message(self) -> None:
        service = PersonContextRetrievalService(RecordingQueryRunner(results=[[]]))

        markdown = service.markdown_for_person("person_missing")

        self.assertEqual(markdown, "the database does not have a record of this person")

    def test_markdown_for_person_returns_empty_for_known_unscoped_person(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
            ]
        )
        service = PersonContextRetrievalService(runner)

        markdown = service.markdown_for_person("person_jamie")

        self.assertEqual(markdown, "")
        self.assertEqual(len(runner.queries), 1)
        self.assertIn("MATCH (p:Person", runner.queries[0].query)
        self.assertTrue(all("type(r) = 'ATTENDED'" not in query.query for query in runner.queries))

    def test_markdown_for_person_does_not_render_recent_episode_summaries(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "# Jamie"}],
            ]
        )
        service = PersonContextRetrievalService(runner)

        markdown = service.markdown_for_person("person_jamie", limit=10)

        self.assertEqual(markdown, "")
        self.assertNotIn("Episode Summaries:", markdown)
        self.assertNotIn("Jamie asked about chargers.", markdown)
        self.assertNotIn("event_1", markdown)
        self.assertNotIn("Design review", markdown)
        self.assertNotIn("Transcript snippets:", markdown)
        self.assertNotIn("2026-06-16T14:00:00+00:00 Jamie: Any chargers?", markdown)
        self.assertEqual(len(runner.queries), 1)
        self.assertTrue(all("type(r) = 'ATTENDED'" not in query.query for query in runner.queries))

    def test_markdown_for_person_scoped_no_match_does_not_fallback_to_events(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [],
            ]
        )
        service = PersonContextRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        markdown = service.markdown_for_person("person_jamie", semantic_scope=" chargers ")

        self.assertEqual(markdown, "no episodes matched the semantic scope: chargers")
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[1].query)
        self.assertTrue(all("type(r) = 'ATTENDED'" not in query.query for query in runner.queries))
        self.assertTrue(all("ORDER BY e.start_time DESC" not in query.query for query in runner.queries[1:]))

    def test_markdown_for_person_does_not_render_scoped_episode_summaries(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [
                    {
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "text": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": None,
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                        "score": 0.8819,
                    }
                ],
            ]
        )
        service = PersonContextRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        markdown = service.markdown_for_person("person_jamie", limit=1, semantic_scope="chargers")

        self.assertEqual(markdown, "")
        self.assertNotIn("Episode Summaries:", markdown)
        self.assertNotIn("Jamie asked about chargers.", markdown)
        self.assertNotIn("episode_1", markdown)
        self.assertNotIn("score=0.882", markdown)
        self.assertNotIn("Jamie: Any chargers?", markdown)
        self.assertTrue(all("type(r) = 'ATTENDED'" not in query.query for query in runner.queries))

    def test_source_for_person_combines_recent_episodes_and_events(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [
                    {
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "text": "Jamie asked about chargers.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": None,
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                    }
                ],
                [
                    {
                        "item_id": "event_1",
                        "item_type": "event",
                        "text": "Design review in room 101.",
                        "start_time": "2026-06-16T15:00:00+00:00",
                        "end_time": "2026-06-16T16:00:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "accepted",
                        "source": "outlook",
                    }
                ],
            ]
        )
        service = PersonContextRetrievalService(runner)

        source = service.source_for_person("person_jamie", limit=10)

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source.person_id, "person_jamie")
        self.assertEqual([item.item_id for item in source.items], ["event_1", "episode_1"])
        self.assertIn("e.transcript AS transcript", runner.queries[1].query)
        self.assertIn("PARTICIPATED_IN", runner.queries[1].query)
        self.assertIn("type(r) = 'ATTENDED'", runner.queries[2].query)
        self.assertIn("properties(r) AS rel_props", runner.queries[2].query)

    def test_source_for_person_parses_timestamped_transcript_lines(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [
                    {
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "text": (
                            "[2026-06-16T14:00:00+00:00] Asha: Can someone review this today?\n"
                            "[2026-06-16T14:05:00+00:00] Jamie: I reviewed it."
                        ),
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": "2026-06-16T14:05:00+00:00",
                        "building_code": "SLACK",
                        "room_id": "C123",
                        "role": "speaker",
                        "source": "slack",
                    }
                ],
                [],
            ]
        )
        service = PersonContextRetrievalService(runner)

        source = service.source_for_person("person_jamie")

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(
            [(line.timestamp, line.speaker, line.text) for line in source.items[0].transcript_lines],
            [
                ("2026-06-16T14:00:00+00:00", "Asha", "Can someone review this today?"),
                ("2026-06-16T14:05:00+00:00", "Jamie", "I reviewed it."),
            ],
        )

    def test_source_for_person_semantic_scope_uses_vector_episode_evidence_only(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [
                    {
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "text": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": None,
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                        "score": 0.72,
                    },
                    {
                        "item_id": "episode_2",
                        "item_type": "episode",
                        "text": "Jamie: I found the adapters.",
                        "start_time": "2026-06-16T15:00:00+00:00",
                        "end_time": None,
                        "building_code": "MAIN",
                        "room_id": "101",
                        "role": "speaker",
                        "source": "caller",
                        "score": 0.88,
                    },
                ],
            ]
        )
        service = PersonContextRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        source = service.source_for_person("person_jamie", limit=10, semantic_scope="chargers")

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual([item.item_id for item in source.items], ["episode_2", "episode_1"])
        self.assertEqual([item.score for item in source.items], [0.88, 0.72])
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[1].query)
        self.assertEqual(runner.queries[1].parameters["person_id"], "person_jamie")
        self.assertEqual(runner.queries[1].parameters["limit"], 10)
        self.assertEqual(runner.queries[1].parameters["candidate_limit"], 50)
        self.assertTrue(all("db.index.vector.queryNodes" in query.query for query in runner.queries[1:]))
        self.assertTrue(all("type(r) = 'ATTENDED'" not in query.query for query in runner.queries))

    def test_source_for_person_whitespace_semantic_scope_uses_unscoped_context(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie", "display_name": "Jamie"}],
                [
                    {
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "text": "Jamie asked about chargers.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
                [],
            ]
        )
        service = PersonContextRetrievalService(runner)

        source = service.source_for_person("person_jamie", semantic_scope="   ")

        self.assertIsNotNone(source)
        self.assertEqual(len(runner.queries), 3)
        self.assertIn("ATTENDED", runner.queries[2].query)

    def test_source_for_person_semantic_scope_requires_embeddings(self) -> None:
        service = PersonContextRetrievalService(
            RecordingQueryRunner(results=[[{"person_id": "person_jamie", "display_name": "Jamie"}]])
        )

        with self.assertRaisesRegex(ValueError, "semantic_scope"):
            service.source_for_person("person_jamie", semantic_scope="chargers")

    def test_source_for_person_returns_none_when_person_is_unknown(self) -> None:
        service = PersonContextRetrievalService(RecordingQueryRunner(results=[[]]))

        self.assertIsNone(service.source_for_person("person_missing"))


if __name__ == "__main__":
    unittest.main()
