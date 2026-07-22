from tests.helpers import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.models import SearchQuery
from tailwag_memory.retrieval import (
    EpisodeRetrievalService,
    EventRetrievalService,
    PersonContextRetrievalService,
    _vector_search_clause,
    recent_episode_rows_for_person,
)
import unittest


class EpisodeRetrievalServiceTest(unittest.TestCase):
    def test_recent_episode_rows_for_person_returns_rows_and_forwards_bounds(self) -> None:
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
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 3})

    def test_recent_episode_rows_for_person_robot_scope_includes_global_and_self(self) -> None:
        runner = RecordingQueryRunner()

        recent_episode_rows_for_person(runner, "person_jamie", 3, robot_id="cody")

        query = runner.queries[0]
        self.assertEqual(
            query.parameters,
            {"person_id": "person_jamie", "robot_id": "cody", "limit": 3},
        )
        self.assertIn("NOT EXISTS { MATCH (:Robot)-[:PARTICIPATED_IN]->(e) }", query.query)
        self.assertIn(
            "EXISTS { MATCH (:Robot {id: $robot_id})-[:PARTICIPATED_IN]->(e) }",
            query.query,
        )

    def test_by_person_uses_recent_episode_helper_rows(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": "2026-06-16T14:05:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "robots": [
                            {
                                "robot_id": "puffle",
                                "display_name": "Puffle",
                                "role": "host",
                                "source": "argos",
                            },
                            {
                                "robot_id": "cody",
                                "display_name": "Cody",
                                "role": "host",
                                "source": "argos",
                            },
                        ],
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.by_person("person_jamie", limit=2)

        self.assertEqual(results[0].episode_id, "episode_1")
        self.assertEqual(results[0].start_time, "2026-06-16T14:00:00+00:00")
        self.assertEqual(results[0].end_time, "2026-06-16T14:05:00+00:00")
        self.assertEqual(results[0].building_code, "MAIN")
        self.assertEqual(results[0].room_id, "101")
        self.assertEqual([robot.robot_id for robot in results[0].robots], ["cody", "puffle"])
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters, {"person_id": "person_jamie", "limit": 2})

    def test_by_robot_uses_stable_id_and_returns_all_episode_robots(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Cody: Welcome.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "building_code": "BOS3",
                        "room_id": "__site__",
                        "robots": [
                            {
                                "robot_id": "cody",
                                "display_name": "Cody Renamed",
                                "role": "host",
                                "source": "argos",
                            },
                            {
                                "robot_id": "assistant",
                                "display_name": "Cody",
                                "role": "assistant",
                                "source": "caller",
                            },
                        ],
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.by_robot("cody", limit=4)

        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(runner.queries[0].parameters, {"robot_id": "cody", "limit": 4})
        self.assertEqual([robot.robot_id for robot in results[0].robots], ["assistant", "cody"])
        self.assertEqual(results[0].robots[1].display_name, "Cody Renamed")

    def test_by_place_returns_episode_time_and_place(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": "2026-06-16T14:05:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.by_place("MAIN", "101", limit=2)

        self.assertEqual(results[0].episode_id, "episode_1")
        self.assertEqual(results[0].start_time, "2026-06-16T14:00:00+00:00")
        self.assertEqual(results[0].end_time, "2026-06-16T14:05:00+00:00")
        self.assertEqual(results[0].building_code, "MAIN")
        self.assertEqual(results[0].room_id, "101")
        self.assertEqual(len(runner.queries), 1)
        self.assertEqual(
            runner.queries[0].parameters,
            {"building_code": "MAIN", "room_id": "101", "limit": 2},
        )

    def test_vector_search_uses_transcript_index(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "score": 0.91,
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.vector_search("chargers")

        self.assertEqual(results[0].episode_id, "episode_1")
        self.assertEqual(results[0].score, 0.91)
        self.assertEqual(results[0].start_time, "2026-06-16T14:00:00+00:00")
        self.assertEqual(results[0].building_code, "MAIN")
        self.assertEqual(results[0].room_id, "101")
        # Index safety guard: vector reads stay on the approved Episode index and label.
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[0].query)
        self.assertIn("WHERE node:Episode", runner.queries[0].query)
        self.assertEqual(results[0].robots, [])
        self.assertEqual(runner.queries[0].parameters["limit"], 10)
        self.assertEqual(len(runner.queries[0].parameters["embedding"]), 8)

    def test_search_clause_rejects_unknown_index_identifiers(self) -> None:
        # Vector index names are interpolated as string literals from a known allowlist.
        with self.assertRaisesRegex(ValueError, "unsupported vector index"):
            _vector_search_clause("episode_transcript_embedding) RETURN 1 //", "node", "limit")

    def test_hybrid_search_includes_graph_filters(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "episode_id": "episode_1",
                        "transcript": "Jamie: Any chargers?",
                        "start_time": "2026-06-16T14:00:00+00:00",
                        "end_time": "2026-06-16T14:05:00+00:00",
                        "building_code": "MAIN",
                        "room_id": "101",
                        "score": 0.91,
                    }
                ]
            ]
        )
        service = EpisodeRetrievalService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.hybrid_search(
            SearchQuery(
                text="chargers",
                person_id="person_jamie",
                building_code="MAIN",
                room_id="101",
                limit=5,
                robot_id="cody",
            )
        )

        params = runner.queries[0].parameters
        self.assertEqual(params["person_id"], "person_jamie")
        self.assertEqual(params["robot_id"], "cody")
        self.assertEqual(params["building_code"], "MAIN")
        self.assertEqual(params["room_id"], "101")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["candidate_limit"], 25)
        self.assertIn(
            "NOT EXISTS { MATCH (:Robot)-[:PARTICIPATED_IN]->(node) }",
            runner.queries[0].query,
        )
        self.assertIn(
            "EXISTS { MATCH (:Robot {id: $robot_id})-[:PARTICIPATED_IN]->(node) }",
            runner.queries[0].query,
        )
        self.assertEqual(results[0].start_time, "2026-06-16T14:00:00+00:00")
        self.assertEqual(results[0].end_time, "2026-06-16T14:05:00+00:00")
        self.assertEqual(results[0].building_code, "MAIN")
        self.assertEqual(results[0].room_id, "101")
        self.assertEqual(len(runner.queries), 1)

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
        self.assertEqual(len(runner.queries), 2)


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
        self.assertEqual(len(runner.queries), 2)
        self.assertEqual(len(runner.queries[1].parameters["embedding"]), 8)

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
        self.assertEqual(len(runner.queries), 2)

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
        self.assertEqual(len(runner.queries), 3)
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 10})
        self.assertEqual(runner.queries[2].parameters, {"person_id": "person_jamie", "limit": 10})

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

        source = service.source_for_person(
            "person_jamie",
            limit=10,
            semantic_scope="chargers",
            robot_id="cody",
        )

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual([item.item_id for item in source.items], ["episode_2", "episode_1"])
        self.assertEqual([item.score for item in source.items], [0.88, 0.72])
        self.assertEqual(len(runner.queries[1].parameters["embedding"]), 8)
        self.assertEqual(runner.queries[1].parameters["person_id"], "person_jamie")
        self.assertEqual(runner.queries[1].parameters["robot_id"], "cody")
        self.assertIn(
            "NOT EXISTS { MATCH (:Robot)-[:PARTICIPATED_IN]->(node) }",
            runner.queries[1].query,
        )
        self.assertEqual(runner.queries[1].parameters["limit"], 10)
        self.assertEqual(runner.queries[1].parameters["candidate_limit"], 50)
        self.assertEqual(len(runner.queries), 2)

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
