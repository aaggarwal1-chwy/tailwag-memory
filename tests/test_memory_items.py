from datetime import datetime, timezone
import json
import unittest

from tests.helpers import (
    RecordingQueryRunner,
    StubConsolidationProvider,
    StubExtractionProvider,
    consolidation_op,
    extraction_op,
    provider_response,
    test_episode,
)
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider, OpenAIConfigurationError
from tailwag_memory.memory_context import PersonMemoryContextService, format_person_memory_markdown
from tailwag_memory.memory_items import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EpisodeMemoryExtractionService,
    MemoryConsolidationService,
    MemoryItemService,
    OpenAIMemoryConsolidationProvider,
    OpenAIMemoryExtractionProvider,
    followup_is_visible,
)
from tailwag_memory.models import EpisodeMentionInput, MemoryItemInput, MemoryItemResult, PersonInput


def _seed_row(episode_id: str) -> dict[str, object]:
    return {
        "episode_id": episode_id,
        "transcript": f"Jamie: robot demos help me understand memory systems. ({episode_id})",
        "start_time": f"2026-06-1{episode_id[-1]}T10:00:00+00:00",
        "transcript_embedding": [0.1] * 8,
    }


def _neighbor_row(episode_id: str) -> dict[str, object]:
    row = _seed_row(episode_id)
    row["score"] = 0.9
    return row


def _memory_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": "mem_existing",
        "person_id": "person_jamie",
        "kind": "preference",
        "key": "likes_robot_demos",
        "summary": "likes: robot demos",
        "source": "live_chat",
        "status": "active",
    }
    row.update(overrides)
    return row


def _followup_row(**overrides: object) -> dict[str, object]:
    values = _memory_row(
        memory_id="mem_followup",
        kind="followup",
        key="cape_cod_trip",
        summary="Ask how the Cape Cod trip went.",
        due_at="2026-06-18T09:00:00+00:00",
        expires_at="2099-07-18T00:00:00+00:00",
    )
    values.update(overrides)
    return values


def _extraction_service(runner: RecordingQueryRunner, provider: object) -> EpisodeMemoryExtractionService:
    return EpisodeMemoryExtractionService(runner, MockOpenAIEmbeddingProvider(dimension=8), provider)


def _consolidation_service(runner: RecordingQueryRunner, provider: object) -> MemoryConsolidationService:
    return MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), provider)


class MemoryItemServiceTest(unittest.TestCase):
    def test_create_item_writes_memory_item_relationships_and_embedding(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        memory_id = service.create_item(
            person_id="person_jamie",
            item=MemoryItemInput(
                kind="preference",
                key="likes_robot_demos",
                summary="likes: hands-on robot demos",
                source="live_chat",
                source_ref="segment_1",
            ),
            supported_by_episode_id="episode_1",
        )

        self.assertTrue(memory_id.startswith("mem_"))
        query = runner.queries[0]
        self.assertIn("CREATE (m:MemoryItem", query.query)
        self.assertNotIn("MERGE (m:MemoryItem", query.query)
        self.assertIn("MemoryItem", query.query)
        self.assertIn("HAS_MEMORY", query.query)
        self.assertIn("SUPPORTED_BY", query.query)
        self.assertEqual(query.parameters["memory_id"], memory_id)
        self.assertEqual(query.parameters["person_id"], "person_jamie")
        self.assertEqual(query.parameters["episode_id"], "episode_1")
        self.assertEqual(len(query.parameters["summary_embedding"]), 8)

    def test_followup_requires_expires_at(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "expires_at"):
            service.create_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="followup",
                    key="cape_cod_trip",
                    summary="Cape Cod trip planned for the weekend.",
                    due_at="2026-06-22T09:00:00+00:00",
                ),
            )

    def test_followup_rejects_expiry_before_due(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "greater than or equal to due_at"):
            service.create_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="followup",
                    key="cape_cod_trip",
                    summary="Cape Cod trip planned for the weekend.",
                    due_at="2026-06-22T09:00:00+00:00",
                    expires_at="2026-06-21T23:59:00+00:00",
                ),
            )

    def test_identity_owned_directory_summary_is_rejected(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "directory"):
            service.create_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="fact",
                    key="team_robotics",
                    summary="team: Robotics",
                ),
            )

    def test_transient_task_status_must_be_followup(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "transient task status"):
            service.create_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="fact",
                    key="checkout_bug",
                    summary="debugging the checkout bug today",
                ),
            )

    def test_transient_task_followup_is_allowed_with_expiry(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        memory_id = service.create_item(
            person_id="person_jamie",
            item=MemoryItemInput(
                kind="followup",
                key="checkout_bug",
                summary="debugging the checkout bug today",
                due_at="2026-06-18T16:00:00+00:00",
                expires_at="2026-06-25T00:00:00+00:00",
            ),
        )

        self.assertEqual(runner.queries[0].parameters["kind"], "followup")
        self.assertEqual(runner.queries[0].parameters["expires_at"], "2026-06-25T00:00:00+00:00")
        self.assertTrue(memory_id.startswith("mem_"))

    def test_same_person_kind_and_key_creates_distinct_memory_items(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))
        item = MemoryItemInput(
            kind="fact",
            key="robot_memory_project",
            summary="working on robot memory",
        )

        first_id = service.create_item(person_id="person_jamie", item=item)
        second_id = service.create_item(person_id="person_jamie", item=item)

        self.assertNotEqual(first_id, second_id)
        create_queries = [query for query in runner.queries if "CREATE (m:MemoryItem" in query.query]
        self.assertEqual(len(create_queries), 2)
        self.assertEqual(create_queries[0].parameters["key"], "robot_memory_project")
        self.assertEqual(create_queries[1].parameters["key"], "robot_memory_project")

    def test_vector_search_scores_memory_items_within_person_scope(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_1",
                        "kind": "fact",
                        "key": "robot_memory",
                        "summary": "working on robot social memory extraction",
                        "source": "live_chat",
                        "status": "active",
                        "score": 0.87,
                    }
                ]
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.vector_search(person_id="person_jamie", text="robot memory", limit=3)

        self.assertEqual(results[0].memory_id, "mem_1")
        self.assertEqual(results[0].score, 0.87)
        self.assertIn("db.index.vector.queryNodes('memory_item_summary_embedding'", runner.queries[0].query)
        self.assertIn("HAS_MEMORY", runner.queries[0].query)
        self.assertIn("SUPERSEDED_BY", runner.queries[0].query)
        self.assertNotIn("vector.similarity.cosine", runner.queries[0].query)
        self.assertEqual(runner.queries[0].parameters["candidate_limit"], 25)

    def test_vector_search_overfetches_before_filtering_expired_items(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_expired",
                        "kind": "followup",
                        "key": "old_trip",
                        "summary": "Old trip follow-up.",
                        "source": "live_chat",
                        "status": "active",
                        "expires_at": "2026-06-20T00:00:00+00:00",
                        "score": 0.99,
                    },
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_1",
                        "kind": "fact",
                        "key": "robot_memory",
                        "summary": "Working on robot memory.",
                        "source": "live_chat",
                        "status": "active",
                        "score": 0.90,
                    },
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_2",
                        "kind": "preference",
                        "key": "demos",
                        "summary": "Likes hands-on demos.",
                        "source": "live_chat",
                        "status": "active",
                        "score": 0.80,
                    },
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_3",
                        "kind": "fact",
                        "key": "extra",
                        "summary": "Extra valid memory.",
                        "source": "live_chat",
                        "status": "active",
                        "score": 0.70,
                    },
                ]
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        results = service.vector_search(
            person_id="person_jamie",
            text="robot memory",
            limit=2,
            now=datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual([item.memory_id for item in results], ["mem_1", "mem_2"])
        self.assertEqual(runner.queries[0].parameters["candidate_limit"], 25)

    def test_vector_search_excludes_superseded_audit_memories(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        self.assertEqual(service.vector_search(person_id="person_jamie", text="family", limit=3), [])

        query = runner.queries[0].query
        self.assertIn("node.status = 'active'", query)
        self.assertIn("SUPERSEDED_BY", query)

    def test_list_active_items_filters_expired_followups(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_old_followup",
                        "kind": "followup",
                        "key": "old_trip",
                        "summary": "Old trip.",
                        "source": "live_chat",
                        "status": "active",
                        "expires_at": "2026-06-20T00:00:00+00:00",
                    }
                ]
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        items = service.list_active_items(
            person_id="person_jamie",
            now=datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc),
            limit=10,
        )

        self.assertEqual(items, [])
        self.assertEqual(runner.queries[0].parameters["limit"], 100)

    def test_internal_address_item_marks_active_followup_and_links_addressing_episode(self) -> None:
        runner = RecordingQueryRunner(results=[[{"memory_id": "mem_followup"}]])
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        addressed = service._address_item(
            "mem_followup",
            addressed_at="2026-06-18T10:30:00+00:00",
            episode_id="episode_answer",
        )

        self.assertTrue(addressed)
        query = runner.queries[0]
        self.assertIn("m.status = 'addressed'", query.query)
        self.assertIn("MERGE (m)-[r:ADDRESSED_BY]->(e)", query.query)
        self.assertIn("r.addressed_at", query.query)
        self.assertNotIn("m.addressed_at", query.query)
        self.assertEqual(query.parameters["memory_id"], "mem_followup")
        self.assertEqual(query.parameters["episode_id"], "episode_answer")
        self.assertEqual(query.parameters["addressed_at"], "2026-06-18T10:30:00+00:00")

    def test_merge_items_copies_support_and_supersedes_source_memories(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"memory_id": "mem_old_spouse"}, {"memory_id": "mem_old_kids"}],
                [],
                [{"linked_count": 3}],
                [{"linked_count": 1}],
                [{"memory_id": "mem_old_kids"}, {"memory_id": "mem_old_spouse"}],
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        result = service.merge_items(
            person_id="person_jamie",
            merged_item=MemoryItemInput(
                kind="fact",
                key="family",
                summary="family: spouse Alex; children Maya and Leo",
                source="calling-system",
                source_ref="consolidation",
            ),
            source_memory_ids=["mem_old_spouse", "mem_old_kids"],
            supported_by_episode_ids=["ep_new"],
        )

        merged_id = runner.queries[1].parameters["memory_id"]
        self.assertEqual(result.merged_memory_id, merged_id)
        self.assertTrue(result.merged_memory_id.startswith("mem_"))
        self.assertIn("CREATE (m:MemoryItem", runner.queries[1].query)
        self.assertEqual(result.superseded_memory_ids, ["mem_old_spouse", "mem_old_kids"])
        self.assertEqual(result.linked_episode_count, 4)
        self.assertEqual(result.skipped_source_memory_ids, [])
        self.assertEqual(runner.queries[0].parameters["memory_ids"], ["mem_old_spouse", "mem_old_kids"])
        self.assertEqual(runner.queries[1].parameters["memory_id"], merged_id)
        self.assertIn("MERGE (merged)-[:SUPPORTED_BY]->(episode)", runner.queries[2].query)
        self.assertEqual(runner.queries[3].parameters["episode_ids"], ["ep_new"])
        self.assertIn("source.status = 'superseded'", runner.queries[4].query)
        self.assertIn("MERGE (source)-[:SUPERSEDED_BY]->(merged)", runner.queries[4].query)

    def test_merge_items_uses_relationship_ownership_not_recomputed_memory_ids(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"memory_id": "mem_from_slack_person_id"}],
                [],
                [{"linked_count": 1}],
                [{"memory_id": "mem_from_slack_person_id"}],
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        result = service.merge_items(
            person_id="person_argos_jamie",
            merged_item=MemoryItemInput(
                kind="fact",
                key="family",
                summary="family: spouse Alex",
                source="calling-system",
            ),
            source_memory_ids=["mem_from_slack_person_id"],
        )

        self.assertEqual(result.skipped_source_memory_ids, [])
        self.assertEqual(result.superseded_memory_ids, ["mem_from_slack_person_id"])
        ownership_query = runner.queries[0]
        self.assertIn("(:Person {id: $person_id})-[:HAS_MEMORY]->(m:MemoryItem)", ownership_query.query)
        self.assertEqual(ownership_query.parameters["person_id"], "person_argos_jamie")

    def test_merge_items_reports_source_memories_not_visible_for_person(self) -> None:
        runner = RecordingQueryRunner(
            results=[[{"memory_id": "mem_valid"}], [], [], [{"memory_id": "mem_valid"}]]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        result = service.merge_items(
            person_id="person_jamie",
            merged_item=MemoryItemInput(
                kind="fact",
                key="family",
                summary="family: spouse Alex",
                source="calling-system",
            ),
            source_memory_ids=["mem_valid", "mem_other_person"],
        )

        self.assertEqual(result.superseded_memory_ids, ["mem_valid"])
        self.assertEqual(result.skipped_source_memory_ids, ["mem_other_person"])

    def test_merge_items_rejects_all_invalid_sources_before_creating_memory(self) -> None:
        runner = RecordingQueryRunner(results=[[]])
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "at least one source memory"):
            service.merge_items(
                person_id="person_jamie",
                merged_item=MemoryItemInput(
                    kind="fact",
                    key="family",
                    summary="family: spouse Alex",
                    source="calling-system",
                ),
                source_memory_ids=["mem_other_person"],
            )

        self.assertEqual(len(runner.queries), 1)
        self.assertFalse(any("MERGE (m:MemoryItem" in query.query for query in runner.queries))

    def test_get_and_list_items_exclude_superseded_audit_memories(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        self.assertIsNone(service.get_item("mem_old"))
        self.assertEqual(service.list_items(person_id="person_jamie", statuses=("superseded",), limit=5), [])

        self.assertIn("coalesce(m.status, 'active') <> 'superseded'", runner.queries[0].query)
        self.assertIn("SUPERSEDED_BY", runner.queries[0].query)
        self.assertIn("coalesce(m.status, 'active') <> 'superseded'", runner.queries[1].query)
        self.assertIn("SUPERSEDED_BY", runner.queries[1].query)

    def test_rejects_invalid_observed_at(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "observed_at"):
            service.create_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="fact",
                    key="robot_memory",
                    summary="working on robot memory",
                    observed_at="not-a-time",
                ),
            )

    def test_candidate_items_prioritizes_pinned_context_then_lexical_and_vector(self) -> None:
        class CandidateService(MemoryItemService):
            def vector_search(self, **kwargs):
                self.vector_kwargs = kwargs
                return [
                    MemoryItemResult(
                        memory_id="mem_future_vector_followup",
                        person_id="person_jamie",
                        kind="followup",
                        key="future_trip",
                        summary="Ask about the future trip.",
                        source="live_chat",
                        status="active",
                        due_at="2099-06-18T09:00:00+00:00",
                        expires_at="2099-07-18T00:00:00+00:00",
                        score=0.95,
                    ),
                    MemoryItemResult(
                        memory_id="mem_vector",
                        person_id="person_jamie",
                        kind="fact",
                        key="robot_memory",
                        summary="robot memory extraction work",
                        source="live_chat",
                        score=0.9,
                    )
                ]

        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_followup",
                        "person_id": "person_jamie",
                        "kind": "followup",
                        "key": "cape_cod_trip",
                        "summary": "Cape Cod trip planned for the weekend.",
                        "source": "live_chat",
                        "status": "active",
                        "due_at": "2026-06-22T09:00:00+00:00",
                        "expires_at": "2099-06-27T23:59:00+00:00",
                    },
                    {
                        "memory_id": "mem_addressed",
                        "person_id": "person_jamie",
                        "kind": "followup",
                        "key": "old_trip",
                        "summary": "Old trip follow-up.",
                        "source": "live_chat",
                        "status": "addressed",
                        "due_at": "2026-06-20T09:00:00+00:00",
                        "expires_at": "2026-06-27T23:59:00+00:00",
                    },
                    {
                        "memory_id": "mem_boundary",
                        "person_id": "person_jamie",
                        "kind": "boundary",
                        "key": "avoid_loud_greetings",
                        "summary": "boundary: avoid loud greetings",
                        "source": "live_chat",
                        "status": "active",
                    },
                    {
                        "memory_id": "mem_pref",
                        "person_id": "person_jamie",
                        "kind": "preference",
                        "key": "preferred_language",
                        "summary": "preferred language: Spanish",
                        "source": "live_chat",
                        "status": "active",
                    },
                    {
                        "memory_id": "mem_lexical",
                        "person_id": "person_jamie",
                        "kind": "fact",
                        "key": "demo_project",
                        "summary": "hands-on robot demo project",
                        "source": "live_chat",
                        "status": "active",
                    },
                ]
            ]
        )
        service = CandidateService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        selected = service.candidate_items(
            person_id="person_jamie",
            transcript="Jamie wants a hands-on robot demo with memory examples.",
            limit=5,
        )

        self.assertEqual(
            [item.memory_id for item in selected],
            ["mem_followup", "mem_boundary", "mem_pref", "mem_lexical", "mem_vector"],
        )
        self.assertNotIn("mem_addressed", [item.memory_id for item in selected])
        self.assertNotIn("mem_future_vector_followup", [item.memory_id for item in selected])
        self.assertEqual(service.vector_kwargs["person_id"], "person_jamie")


class MemoryConsolidationServiceTest(unittest.TestCase):
    def test_consolidation_uses_default_minimum_four_evidence_episodes(self) -> None:
        self.assertEqual(DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES, 4)

    def test_consolidate_person_creates_memory_with_four_valid_supporting_episodes(self) -> None:
        provider = StubConsolidationProvider(
            provider_response(consolidation_op(summary="uses hands-on robot demos to understand memory systems"))
        )
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
                [],
                [{"linked_count": 4}],
            ]
        )
        service = _consolidation_service(runner, provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertTrue(result.provider_called)
        self.assertEqual(len(result.created_memory_ids), 1)
        self.assertEqual(result.skipped_ops, [])
        self.assertEqual(provider.calls[0]["min_evidence_episodes"], 4)
        self.assertEqual(
            [item["episode_id"] for item in provider.calls[0]["episode_clusters"][0]],
            ["ep1", "ep2", "ep3", "ep4"],
        )
        self.assertIn("db.index.vector.queryNodes('episode_transcript_embedding'", runner.queries[1].query)
        self.assertIn("WHERE node:Episode", runner.queries[1].query)
        memory_query = [query for query in runner.queries if "CREATE (m:MemoryItem" in query.query][-1]
        self.assertEqual(memory_query.parameters["source_ref"], "consolidation")
        link_query = runner.queries[-1]
        self.assertEqual(link_query.parameters["episode_ids"], ["ep1", "ep2", "ep3", "ep4"])
        self.assertIn("MERGE (m)-[:SUPPORTED_BY]->(e)", link_query.query)

    def test_consolidation_skips_operation_when_valid_evidence_drops_below_four(self) -> None:
        provider = StubConsolidationProvider(
            provider_response(consolidation_op(supported_episode_ids=["ep1", "ep2", "ep3", "ep_missing"]))
        )
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = _consolidation_service(runner, provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertIn("unsupported_episode_id", {item["reason"] for item in result.skipped_ops})
        self.assertIn("insufficient_valid_evidence", {item["reason"] for item in result.skipped_ops})
        self.assertFalse(any("CREATE (m:MemoryItem" in query.query for query in runner.queries))

    def test_consolidation_skips_unknown_operations(self) -> None:
        provider = StubConsolidationProvider(
            provider_response(
                consolidation_op(op="replace", memory_id="mem_existing"),
                consolidation_op(op="retire", memory_id="mem_missing"),
            )
        )
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = _consolidation_service(runner, provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertEqual({item["reason"] for item in result.skipped_ops}, {"unknown_operation"})
        self.assertFalse(any("SET m.summary" in query.query for query in runner.queries))
        self.assertFalse(any("status = 'archived'" in query.query for query in runner.queries))

    def test_consolidation_merges_related_candidate_memories(self) -> None:
        provider = StubConsolidationProvider(
            provider_response(
                consolidation_op(
                    op="merge",
                    memory_ids=["mem_spouse", "mem_kids"],
                    key="family",
                    summary="family: spouse Alex; children Maya and Leo",
                )
            )
        )
        spouse = {
            "memory_id": "mem_spouse",
            "person_id": "person_jamie",
            "kind": "fact",
            "key": "spouse",
            "summary": "spouse: Alex",
            "source": "live_chat",
            "status": "active",
        }
        kids = {
            "memory_id": "mem_kids",
            "person_id": "person_jamie",
            "kind": "fact",
            "key": "kids",
            "summary": "children: Maya and Leo",
            "source": "live_chat",
            "status": "active",
        }
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [spouse, kids],
                [{"memory_id": "mem_spouse"}, {"memory_id": "mem_kids"}],
                [],
                [{"linked_count": 2}],
                [{"linked_count": 4}],
                [{"memory_id": "mem_kids"}, {"memory_id": "mem_spouse"}],
            ]
        )
        service = _consolidation_service(runner, provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        memory_queries = [query for query in runner.queries if "CREATE (m:MemoryItem" in query.query]
        merged_id = memory_queries[-1].parameters["memory_id"]
        self.assertEqual(result.created_memory_ids, [merged_id])
        self.assertTrue(merged_id.startswith("mem_"))
        self.assertEqual(result.superseded_memory_ids, ["mem_spouse", "mem_kids"])
        self.assertEqual(result.skipped_ops, [])
        self.assertTrue(any("SUPERSEDED_BY" in query.query for query in runner.queries))

    def test_consolidation_rejects_nonempty_provider_metadata(self) -> None:
        provider = StubConsolidationProvider(provider_response(consolidation_op(metadata={"extra": True})))
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = _consolidation_service(runner, provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertIn("memory consolidation metadata must be empty", {item["reason"] for item in result.skipped_ops})
        self.assertFalse(any("MERGE (m:MemoryItem" in query.query for query in runner.queries))

    def test_consolidation_skips_provider_when_fewer_than_four_seed_episodes(self) -> None:
        runner = RecordingQueryRunner(results=[[_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3")]])
        service = _consolidation_service(
            runner,
            StubConsolidationProvider(error=AssertionError("provider should not be called")),
        )

        result = service.consolidate_person("person_jamie")

        self.assertFalse(result.provider_called)
        self.assertEqual(result.created_memory_ids, [])
        self.assertEqual(len(runner.queries), 1)

    def test_consolidate_all_isolates_per_person_errors(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie"}],
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = _consolidation_service(
            runner,
            StubConsolidationProvider(error=RuntimeError("provider unavailable")),
        )

        result = service.consolidate_all(person_limit=5, cluster_limit=1)

        self.assertEqual(result.person_results[0].person_id, "person_jamie")
        self.assertEqual(result.person_results[0].error, "provider unavailable")
        self.assertEqual(result.memory_errors, [{"person_id": "person_jamie", "error": "provider unavailable"}])


class MemoryItemMarkdownTest(unittest.TestCase):
    def test_followup_visibility_is_inclusive_between_due_and_expiry(self) -> None:
        item = MemoryItemResult(
            memory_id="mem_followup",
            person_id="person_jamie",
            kind="followup",
            key="cape_cod_trip",
            summary="Cape Cod trip planned for the weekend.",
            source="live_chat",
            due_at="2026-06-22T09:00:00+00:00",
            expires_at="2026-06-27T23:59:00+00:00",
        )

        self.assertTrue(
            followup_is_visible(
                item,
                now=datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            followup_is_visible(
                item,
                now=datetime(2026, 6, 27, 23, 59, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            followup_is_visible(
                item,
                now=datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc),
            )
        )

    def test_markdown_excludes_addressed_followups(self) -> None:
        markdown = format_person_memory_markdown(
            [
                MemoryItemResult(
                    memory_id="mem_followup",
                    person_id="person_jamie",
                    kind="followup",
                    key="cape_cod_trip",
                    summary="Cape Cod trip planned for the weekend.",
                    source="live_chat",
                    status="addressed",
                    due_at="2026-06-22T09:00:00+00:00",
                    expires_at="2026-06-27T23:59:00+00:00",
                )
            ],
            now=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        )

        self.assertNotIn("Potential Follow-Ups:", markdown)
        self.assertNotIn("Cape Cod trip", markdown)

    def test_markdown_context_groups_sections_and_omits_empty_sections(self) -> None:
        now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
        items = [
            MemoryItemResult(
                memory_id="mem_boundary",
                person_id="person_jamie",
                kind="boundary",
                key="avoid_loud_greetings",
                summary="boundary: avoid loud surprise greetings",
                source="live_chat",
                observed_at="2026-06-16T10:00:00+00:00",
            ),
            MemoryItemResult(
                memory_id="mem_preference",
                person_id="person_jamie",
                kind="preference",
                key="preferred_language",
                summary="preferred language: Spanish",
                source="live_chat",
                observed_at="2026-06-16T09:00:00+00:00",
            ),
            MemoryItemResult(
                memory_id="mem_pet",
                person_id="person_jamie",
                kind="pet",
                key="pet_luna",
                summary="pet: Luna (dog): recovering well after surgery",
                source="live_chat",
                observed_at="2026-06-16T08:00:00+00:00",
            ),
            MemoryItemResult(
                memory_id="mem_fact",
                person_id="person_jamie",
                kind="fact",
                key="robot_memory_project",
                summary="working on robot social memory extraction",
                source="live_chat",
                observed_at="2026-06-15T08:00:00+00:00",
            ),
            MemoryItemResult(
                memory_id="mem_followup",
                person_id="person_jamie",
                kind="followup",
                key="cape_cod_trip",
                summary="Cape Cod trip planned for the weekend.",
                source="live_chat",
                due_at="2026-06-22T09:00:00+00:00",
                expires_at="2026-06-27T23:59:00+00:00",
            ),
        ]

        markdown = format_person_memory_markdown(
            items,
            recent_episode_lines=["2026-06-16: Jamie mentioned Luna had a vet visit tomorrow."],
            now=now,
        )

        self.assertIn("[PERSON MEMORY]", markdown)
        self.assertLess(markdown.index("Boundaries:"), markdown.index("Preferences:"))
        self.assertIn("- boundary: avoid loud surprise greetings", markdown)
        self.assertIn("Potential Follow-Ups:", markdown)
        self.assertIn("- Cape Cod trip planned for the weekend.", markdown)
        self.assertIn("Recent Episodes:", markdown)
        self.assertNotIn("Notes:", markdown)

    def test_markdown_prioritizes_semantic_hits_and_sanitizes_lines(self) -> None:
        items = [
            MemoryItemResult(
                memory_id="mem_new",
                person_id="person_jamie",
                kind="fact",
                key="newer",
                summary="# newer but less relevant\nsecond line",
                source="live_chat",
                observed_at="2026-06-20T08:00:00+00:00",
            ),
            MemoryItemResult(
                memory_id="mem_old_match",
                person_id="person_jamie",
                kind="fact",
                key="older",
                summary="- older but semantically relevant\nwith continuation",
                source="live_chat",
                observed_at="2026-06-15T08:00:00+00:00",
                score=0.91,
            ),
        ]

        markdown = format_person_memory_markdown(items, now=datetime(2026, 6, 23, tzinfo=timezone.utc), limit=1)

        self.assertIn("- older but semantically relevant with continuation", markdown)
        self.assertNotIn("newer but less relevant", markdown)
        self.assertNotIn("\nwith continuation", markdown)

    def test_empty_markdown_context_returns_empty_string(self) -> None:
        self.assertEqual(format_person_memory_markdown([], recent_episode_lines=[]), "")


class PersonMemoryContextServiceTest(unittest.TestCase):
    def test_markdown_for_person_includes_boundaries_before_preferences_and_facts_with_recent_episodes(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_pref",
                        "kind": "preference",
                        "key": "preferred_language",
                        "summary": "preferred language: Spanish",
                        "source": "live_chat",
                        "status": "active",
                        "observed_at": "2026-06-18T09:00:00+00:00",
                    },
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_fact",
                        "kind": "fact",
                        "key": "robot_memory_project",
                        "summary": "working on robot social memory extraction",
                        "source": "live_chat",
                        "status": "active",
                        "observed_at": "2026-06-17T09:00:00+00:00",
                    },
                    {
                        "person_id": "person_jamie",
                        "memory_id": "mem_boundary",
                        "kind": "boundary",
                        "key": "avoid_loud_greetings",
                        "summary": "boundary: avoid loud surprise greetings",
                        "source": "live_chat",
                        "status": "active",
                        "observed_at": "2026-06-16T09:00:00+00:00",
                    },
                ],
                [
                    {
                        "episode_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "transcript": "Jamie: Luna has a vet visit tomorrow.\nCasey: I can drive.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
            ]
        )
        service = PersonMemoryContextService(runner)

        markdown = service.markdown_for_person(
            "person_jamie",
            now=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
            memory_limit=12,
            recent_episode_limit=1,
        )

        self.assertIn("Boundaries:", markdown)
        self.assertIn("- boundary: avoid loud surprise greetings", markdown)
        self.assertIn("Preferences:", markdown)
        self.assertIn("- preferred language: Spanish", markdown)
        self.assertIn("Facts:", markdown)
        self.assertIn("- working on robot social memory extraction", markdown)
        self.assertIn("Recent Episodes:", markdown)
        self.assertIn("- 2026-06-16: Jamie: Luna has a vet visit tomorrow.", markdown)
        self.assertNotIn("Casey: I can drive.", markdown)
        self.assertLess(markdown.index("Boundaries:"), markdown.index("Preferences:"))
        self.assertLess(markdown.index("Boundaries:"), markdown.index("Facts:"))
        self.assertLess(markdown.index("Facts:"), markdown.index("Recent Episodes:"))
        self.assertEqual(runner.queries[0].parameters["person_id"], "person_jamie")
        self.assertEqual(runner.queries[0].parameters["statuses"], ["active"])
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 1})

    def test_markdown_for_person_uses_shared_recent_episode_rows(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [],
                [
                    {
                        "episode_id": "episode_1",
                        "item_id": "episode_1",
                        "item_type": "episode",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "transcript": "Assistant: Do you need anything?\nJamie: Luna has a vet visit tomorrow.",
                        "text": "Assistant: Do you need anything?\nJamie: Luna has a vet visit tomorrow.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
            ]
        )
        service = PersonMemoryContextService(runner)

        markdown = service.markdown_for_person(" person_jamie ", recent_episode_limit=2)

        self.assertIn("Recent Episodes:", markdown)
        self.assertIn("- 2026-06-16: Jamie: Luna has a vet visit tomorrow.", markdown)
        self.assertNotIn("Assistant: Do you need anything?", markdown)
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 2})
        self.assertIn("e.id AS episode_id", runner.queries[1].query)
        self.assertIn("'episode' AS item_type", runner.queries[1].query)

    def test_markdown_for_person_matches_person_id_speaker_when_display_name_is_missing(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [],
                [
                    {
                        "episode_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": None,
                        "transcript": "person_jamie: I like robot demos.\nAssistant: Noted.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
            ]
        )
        service = PersonMemoryContextService(runner)

        markdown = service.markdown_for_person("person_jamie", recent_episode_limit=1)

        self.assertIn("- 2026-06-16: person_jamie: I like robot demos.", markdown)
        self.assertNotIn("Assistant: Noted.", markdown)

    def test_markdown_for_person_splits_single_line_speaker_turns(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [],
                [
                    {
                        "episode_id": "episode_1",
                        "person_id": "person_jamie",
                        "display_name": "Jamie",
                        "speaker_labels": ["Jamie", "Assistant"],
                        "transcript": "Jamie: Do we have chargers? Assistant: They are at the desk.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
            ]
        )
        service = PersonMemoryContextService(runner)

        markdown = service.markdown_for_person("person_jamie", recent_episode_limit=1)

        self.assertIn("- 2026-06-16: Jamie: Do we have chargers?", markdown)
        self.assertNotIn("Assistant: They are at the desk.", markdown)


class EpisodeMemoryExtractionServiceTest(unittest.TestCase):
    def test_extract_for_episode_processes_all_participants_and_scopes_provider_calls(self) -> None:
        provider = StubExtractionProvider(
            provider_response(
                extraction_op(
                    memory_id="mem_provider_requested",
                    kind="preference",
                    key="likes_robot_demos",
                    summary="likes: hands-on robot demos",
                )
            )
        )
        runner = RecordingQueryRunner(results=[[], [], [], [], [], []])
        service = _extraction_service(runner, provider)
        episode = test_episode(
            transcript="Jamie: I like robot demos.\nCasey: I prefer quiet greetings.",
            participants=[
                PersonInput(id="person_jamie", display_name="Jamie", role="speaker", source="live_chat"),
                PersonInput(id="person_casey", display_name="Casey", role="participant", source="live_chat"),
            ],
        )

        result = service.extract_for_episode(episode, speaker_only=False)

        self.assertEqual(result.episode_id, "episode_1")
        self.assertEqual([item.person_id for item in result.memory_results], ["person_jamie", "person_casey"])
        self.assertEqual([call["target_display_name"] for call in provider.calls], ["Jamie", "Casey"])
        self.assertEqual(result.memory_errors, [])

    def test_extract_for_episode_ignores_mention_only_people(self) -> None:
        provider = StubExtractionProvider()
        service = _extraction_service(
            RecordingQueryRunner(),
            provider,
        )
        episode = test_episode(
            episode_id="episode_mention_only",
            transcript="Jamie: Can Chandra review this?",
            participants=[],
            mentioned_people=[
                EpisodeMentionInput(
                    person=PersonInput(id="person_chandra", display_name="Chandra", role="mentioned"),
                    source="slack",
                )
            ],
        )

        result = service.extract_for_episode(episode, speaker_only=False)

        self.assertEqual(result.episode_id, "episode_mention_only")
        self.assertEqual(result.memory_results, [])
        self.assertEqual(result.memory_errors, [])
        self.assertEqual(provider.calls, [])
        with self.assertRaisesRegex(ValueError, "not linked"):
            service.extract_for_episode(episode, person_id="person_chandra")

    def test_extract_for_episode_normalizes_robot_user_label_before_provider_call(self) -> None:
        provider = StubExtractionProvider()
        runner = RecordingQueryRunner(results=[[], []])
        service = _extraction_service(runner, provider)
        episode = test_episode(
            transcript="User: I like robot demos.\nAssistant: Noted.",
            building_code="ARGOS",
            room_id="realtime",
            participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
        )

        service.extract_for_episode(episode)

        self.assertEqual(provider.calls[0]["target_display_name"], "Jamie")
        self.assertEqual(provider.calls[0]["transcript"], "Jamie: I like robot demos.\nAssistant: Noted.")

    def test_extract_for_stored_episode_defaults_to_speakers_and_falls_back_to_all(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "id": "episode_1",
                        "episode_type": "conversation",
                        "start_time": "2026-06-18T10:00:00+00:00",
                        "transcript": "Jamie: hello",
                        "retention_class": "standard",
                        "building_code": "MAIN",
                        "room_id": "101",
                    }
                ],
                [
                    {"id": "person_casey", "display_name": "Casey", "role": "participant", "source": "live_chat"},
                    {"id": "person_jamie", "display_name": "Jamie", "role": "speaker", "source": "live_chat"},
                ],
                [],
                [],
            ]
        )
        provider = StubExtractionProvider()
        service = _extraction_service(runner, provider)

        result = service.extract_for_stored_episode("episode_1")

        self.assertEqual([item.person_id for item in result.memory_results], ["person_jamie"])
        self.assertEqual([call["person_id"] for call in provider.calls], ["person_jamie"])

    def test_extract_for_episode_returns_per_person_error_without_failing_episode(self) -> None:
        runner = RecordingQueryRunner(results=[[], []])
        service = _extraction_service(
            runner,
            StubExtractionProvider(errors_by_person={"person_casey": RuntimeError("provider unavailable")}),
        )
        episode = test_episode(
            transcript="Jamie: hello\nCasey: hello",
            participants=[
                PersonInput(id="person_jamie", display_name="Jamie", role="speaker"),
                PersonInput(id="person_casey", display_name="Casey", role="speaker"),
            ],
        )

        result = service.extract_for_episode(episode)

        self.assertEqual(result.memory_results[0].error, None)
        self.assertEqual(result.memory_results[1].error, "provider unavailable")
        self.assertEqual(result.memory_errors, [{"person_id": "person_casey", "error": "provider unavailable"}])


class EpisodeMemoryOperationTest(unittest.TestCase):
    def test_extract_for_episode_applies_create_operations(self) -> None:
        provider = StubExtractionProvider(
            provider_response(
                extraction_op(
                    memory_id="mem_provider_requested",
                    kind="preference",
                    key="likes_robot_demos",
                    summary="likes: hands-on robot demos",
                )
            )
        )
        runner = RecordingQueryRunner(results=[[], [], []])
        service = _extraction_service(runner, provider)

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_segment_1",
                start_time="2026-06-16T10:00:00+00:00",
                transcript="Jamie: I like hands-on robot demos.",
                participants=[
                    PersonInput(
                        id="person_jamie",
                        display_name="Jamie",
                        role="speaker",
                        source="calling-system",
                    )
                ],
            )
        )

        self.assertEqual(result.episode_id, "episode_segment_1")
        self.assertTrue(result.memory_results[0].update_requested)
        self.assertEqual(len(result.memory_results[0].created_memory_ids), 1)
        self.assertEqual(provider.calls[0]["person_id"], "person_jamie")
        self.assertEqual(provider.calls[0]["target_display_name"], "Jamie")
        self.assertEqual(provider.calls[0]["existing_memories"], [])
        self.assertEqual(provider.calls[0]["current_time"], "2026-06-16T10:00:00+00:00")
        memory_queries = [query for query in runner.queries if "CREATE (m:MemoryItem" in query.query]
        self.assertTrue(memory_queries)
        memory_params = memory_queries[-1].parameters
        self.assertEqual(memory_params["episode_id"], "episode_segment_1")
        self.assertEqual(memory_params["source"], "calling-system")
        self.assertEqual(memory_params["source_ref"], "episode_segment_1")
        self.assertEqual(memory_params["observed_at"], "2026-06-16T10:00:00+00:00")
        self.assertNotEqual(memory_params["memory_id"], "mem_provider_requested")

    def test_extract_for_episode_skips_provider_followup_already_expired_at_processing_time(self) -> None:
        runner = RecordingQueryRunner(results=[[], []])
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(
                    extraction_op(
                        kind="followup",
                        key="old_demo",
                        summary="Ask how the old demo went.",
                        due_at="2000-01-02T08:00:00+00:00",
                        expires_at="2000-01-03T08:00:00+00:00",
                    )
                )
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_old",
                start_time="2000-01-01T10:00:00+00:00",
                transcript="Jamie: The demo is tomorrow.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.created_memory_ids, [])
        self.assertEqual(person_result.skipped_ops[0]["reason"], "followup_already_expired")
        self.assertFalse(any("CREATE (m:MemoryItem" in query.query for query in runner.queries))

    def test_extract_for_episode_skips_unknown_and_bad_operations(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    _memory_row(source_ref="segment_old", metadata_json='{"origin":"old"}')
                ],
                [],
                [
                    _memory_row(source_ref="segment_old", metadata_json='{"origin":"old"}')
                ],
                [{"memory_id": "mem_existing"}],
                [{"memory_id": "mem_existing"}],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(
                    extraction_op(op="replace", memory_id="mem_existing", summary="updated robot demo preference"),
                    extraction_op(op="retire", memory_id="mem_existing"),
                    extraction_op(op="retire", memory_id="mem_unknown"),
                    {"op": "bad-op"},
                    "not-a-dict",
                    {"op": "noop"},
                )
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_segment_2",
                start_time="2026-06-17T10:00:00+00:00",
                transcript="Jamie: I still like robot demos.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.created_memory_ids, [])
        self.assertEqual(person_result.addressed_memory_ids, [])
        self.assertEqual(person_result.supported_memory_ids, [])
        self.assertEqual(len(person_result.skipped_ops), 5)
        self.assertIn("unknown_operation", {item["reason"] for item in person_result.skipped_ops})
        self.assertIn("unknown_memory_id", {item["reason"] for item in person_result.skipped_ops})
        self.assertFalse(any("SET m.summary" in query.query for query in runner.queries))
        self.assertFalse(any("status = 'archived'" in query.query for query in runner.queries))

    def test_extract_for_episode_applies_address_operations_for_followups_at_play(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [_followup_row()],
                [],
                [{"memory_id": "mem_followup"}],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(extraction_op(op="address", memory_id="mem_followup"))
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_answer",
                start_time="2026-06-20T10:00:00+00:00",
                end_time="2026-06-20T10:30:00+00:00",
                transcript="Jamie: Cape Cod was wonderful.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.addressed_memory_ids, ["mem_followup"])
        address_query = runner.queries[-1]
        self.assertIn("ADDRESSED_BY", address_query.query)
        self.assertEqual(address_query.parameters["memory_id"], "mem_followup")
        self.assertEqual(address_query.parameters["episode_id"], "episode_answer")
        self.assertTrue(address_query.parameters["addressed_at"])

    def test_extract_for_episode_reports_address_noop(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [_followup_row()],
                [],
                [],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(extraction_op(op="address", memory_id="mem_followup"))
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_answer",
                start_time="2026-06-20T10:00:00+00:00",
                transcript="Jamie: Cape Cod was wonderful.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.addressed_memory_ids, [])
        self.assertEqual(person_result.skipped_ops[0]["reason"], "address_noop")

    def test_extract_for_episode_applies_support_operations_for_followups_at_play(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [_followup_row()],
                [],
                [{"linked_count": 1}],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(extraction_op(op="support", memory_id="mem_followup"))
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_related",
                start_time="2026-06-20T10:00:00+00:00",
                end_time="2026-06-20T10:30:00+00:00",
                transcript="Jamie: We are still planning Cape Cod.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.supported_memory_ids, ["mem_followup"])
        self.assertEqual(person_result.addressed_memory_ids, [])
        support_query = runner.queries[-1]
        self.assertIn("MERGE (m)-[:SUPPORTED_BY]->(e)", support_query.query)
        self.assertEqual(support_query.parameters["memory_id"], "mem_followup")
        self.assertEqual(support_query.parameters["episode_ids"], ["episode_related"])

    def test_extract_for_episode_reports_support_noop(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [_followup_row()],
                [],
                [{"linked_count": 0}],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(extraction_op(op="support", memory_id="mem_followup"))
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_related",
                start_time="2026-06-20T10:00:00+00:00",
                transcript="Jamie: We are still planning Cape Cod.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.supported_memory_ids, [])
        self.assertEqual(person_result.skipped_ops[0]["reason"], "support_noop")

    def test_extract_for_episode_skips_address_or_support_for_invalid_candidates(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    _memory_row(memory_id="mem_fact", kind="fact", key="robot_memory", summary="working on robot memory"),
                    _followup_row(
                        memory_id="mem_future",
                        key="future_trip",
                        summary="Ask about the future trip.",
                        due_at="2099-06-18T09:00:00+00:00",
                    ),
                ],
                [],
            ]
        )
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(
                    *(
                        extraction_op(op=op, memory_id=memory_id)
                        for op in ["address", "support"]
                        for memory_id in ["mem_fact", "mem_future", "mem_unknown"]
                    )
                )
            ),
        )

        result = service.extract_for_episode(
            test_episode(
                episode_id="episode_answer",
                start_time="2026-06-20T10:00:00+00:00",
                transcript="Jamie: Robot memory is going well.",
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.addressed_memory_ids, [])
        self.assertEqual(person_result.supported_memory_ids, [])
        self.assertEqual(
            {item["reason"] for item in person_result.skipped_ops},
            {"address_non_followup", "support_non_followup", "unknown_memory_id"},
        )
        self.assertFalse(any("ADDRESSED_BY" in query.query for query in runner.queries))
        self.assertFalse(any("MERGE (m)-[:SUPPORTED_BY]->(e)" in query.query for query in runner.queries))

    def test_metadata_value_alias_is_not_accepted(self) -> None:
        runner = RecordingQueryRunner(results=[[], [], []])
        service = _extraction_service(
            runner,
            StubExtractionProvider(
                provider_response(
                    extraction_op(
                        kind="fact",
                        key="robot_memory",
                        summary="working on robot memory",
                        value={"legacy": True},
                    )
                )
            ),
        )

        service.extract_for_episode(
            test_episode(
                episode_id="episode_segment_3",
                start_time="2026-06-17T10:00:00+00:00",
                transcript="Jamie: I work on robot memory.",
            )
        )

        memory_queries = [query for query in runner.queries if "CREATE (m:MemoryItem" in query.query]
        self.assertEqual(memory_queries[-1].parameters["metadata_json"], "{}")


class OpenAIMemoryExtractionProviderTest(unittest.TestCase):
    def test_extract_requests_structured_output_schema(self) -> None:
        class FakeResponses:
            def __init__(self) -> None:
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return {"output_text": '{"update": false, "ops": []}'}

        class FakeClient:
            def __init__(self) -> None:
                self.responses = FakeResponses()

        client = FakeClient()
        provider = OpenAIMemoryExtractionProvider(client=client)

        payload = provider.extract(
            person_id="person_jamie",
            transcript="Jamie: hello",
            existing_memories=[],
            current_time="2026-06-17T12:00:00+00:00",
        )

        self.assertEqual(payload, {"update": False, "ops": []})
        text_format = client.responses.kwargs["text"]["format"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertEqual(text_format["name"], "memory_extraction")
        self.assertTrue(text_format["strict"])
        metadata_schema = text_format["schema"]["properties"]["ops"]["items"]["properties"]["metadata"]
        self.assertEqual(metadata_schema["additionalProperties"], False)
        self.assertEqual(metadata_schema["properties"], {})
        developer_prompt = client.responses.kwargs["input"][0]["content"]
        headings = (
            "Task:",
            "Durability rules:",
            "Allowed kinds:",
            "Allowed operations:",
            "Create rules:",
            "Address rules:",
            "Followup timing rules:",
            "Do not store:",
        )
        heading_positions = []
        for heading in headings:
            self.assertIn(heading, developer_prompt)
            self.assertEqual(developer_prompt.count(heading), 1)
            heading_positions.append(developer_prompt.index(heading))
        self.assertEqual(heading_positions, sorted(heading_positions))
        self.assertIn("stay relevant for weeks at a time", developer_prompt)
        self.assertIn("Insignificant observations", developer_prompt)
        self.assertIn("future conversation more fruitful", developer_prompt)
        self.assertIn("bugs being debugged today", developer_prompt)
        self.assertIn("must be followup, not fact or preference", developer_prompt)
        self.assertIn("Use support", developer_prompt)
        self.assertIn("still open", developer_prompt)
        self.assertIn("Use the current_time value as the evidence time", developer_prompt)
        self.assertIn("If the timing is", developer_prompt)
        self.assertIn("vague, do not create a followup", developer_prompt)
        self.assertIn("first useful opportunity after that window", developer_prompt)
        self.assertIn("expire within a week", developer_prompt)
        self.assertIn("Use address", developer_prompt)
        self.assertIn("active, unaddressed, currently relevant", developer_prompt)
        op_schema = text_format["schema"]["properties"]["ops"]["items"]["properties"]["op"]
        self.assertEqual(op_schema["enum"], ["create", "address", "support", "noop"])

    def test_extract_reads_sdk_response_shape(self) -> None:
        class FakeContent:
            text = '{"update": false, "ops": []}'

        class FakeOutput:
            content = [FakeContent()]

        class FakeResponse:
            output = [FakeOutput()]

        class FakeResponses:
            def create(self, **kwargs):
                del kwargs
                return FakeResponse()

        class FakeClient:
            def __init__(self) -> None:
                self.responses = FakeResponses()

        provider = OpenAIMemoryExtractionProvider(client=FakeClient())

        self.assertEqual(
            provider.extract(
                person_id="person_jamie",
                transcript="Jamie: hello",
                existing_memories=[],
                current_time="2026-06-17T12:00:00+00:00",
            ),
            {"update": False, "ops": []},
        )

    def test_extract_requires_api_key_without_injected_client(self) -> None:
        provider = OpenAIMemoryExtractionProvider()

        with self.assertRaisesRegex(OpenAIConfigurationError, "OpenAI memory extraction"):
            provider.extract(
                person_id="person_jamie",
                transcript="Jamie: hello",
                existing_memories=[],
                current_time="2026-06-17T12:00:00+00:00",
            )


class OpenAIMemoryConsolidationProviderTest(unittest.TestCase):
    def test_consolidate_requests_structured_output_with_support_ids(self) -> None:
        class FakeResponses:
            def __init__(self) -> None:
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return {"output_text": '{"update": false, "ops": []}'}

        class FakeClient:
            def __init__(self) -> None:
                self.responses = FakeResponses()

        client = FakeClient()
        provider = OpenAIMemoryConsolidationProvider(client=client)

        payload = provider.consolidate(
            person_id="person_jamie",
            existing_memories=[],
            episode_clusters=[
                [
                    {
                        "episode_id": "ep1",
                        "transcript": "Jamie: I like robot demos.",
                        "start_time": "2026-06-18T10:00:00+00:00",
                        "end_time": "",
                    }
                ]
            ],
            current_time="2026-06-18T12:00:00+00:00",
            min_evidence_episodes=4,
        )

        self.assertEqual(payload, {"update": False, "ops": []})
        text_format = client.responses.kwargs["text"]["format"]
        self.assertEqual(text_format["name"], "memory_consolidation")
        op_schema = text_format["schema"]["properties"]["ops"]["items"]
        self.assertEqual(op_schema["properties"]["op"]["enum"], ["create", "merge", "noop"])
        self.assertIn("memory_ids", op_schema["properties"])
        self.assertIn("memory_ids", op_schema["required"])
        self.assertIn("supported_episode_ids", op_schema["properties"])
        self.assertIn("supported_episode_ids", op_schema["required"])
        developer_prompt = client.responses.kwargs["input"][0]["content"]
        self.assertIn("Do not invent episode IDs", developer_prompt)
        self.assertIn("required minimum number", developer_prompt)
        self.assertIn("Merge related memories", developer_prompt)
        self.assertIn("source memory IDs", developer_prompt)
        self.assertIn("skip vague followups rather than guessing", developer_prompt)
        user_payload = json.loads(client.responses.kwargs["input"][1]["content"])
        self.assertEqual(user_payload["min_evidence_episodes"], 4)
        self.assertEqual(user_payload["episode_clusters"][0][0]["episode_id"], "ep1")

    def test_consolidate_rejects_malformed_json_with_specific_error(self) -> None:
        class FakeResponses:
            def create(self, **kwargs):
                del kwargs
                return {"output_text": "not-json"}

        class FakeClient:
            def __init__(self) -> None:
                self.responses = FakeResponses()

        provider = OpenAIMemoryConsolidationProvider(client=FakeClient())

        with self.assertRaisesRegex(ValueError, "OpenAI memory consolidation did not return valid JSON"):
            provider.consolidate(
                person_id="person_jamie",
                existing_memories=[],
                episode_clusters=[],
                current_time="2026-06-18T12:00:00+00:00",
                min_evidence_episodes=4,
            )

    def test_consolidate_requires_api_key_without_injected_client(self) -> None:
        provider = OpenAIMemoryConsolidationProvider()

        with self.assertRaisesRegex(OpenAIConfigurationError, "OpenAI memory consolidation"):
            provider.consolidate(
                person_id="person_jamie",
                existing_memories=[],
                episode_clusters=[],
                current_time="2026-06-18T12:00:00+00:00",
                min_evidence_episodes=4,
            )


if __name__ == "__main__":
    unittest.main()
