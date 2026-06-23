from datetime import datetime, timezone
import json
import unittest

from tailwag_memory.db import RecordingQueryRunner
from tailwag_memory.embeddings import MockOpenAIEmbeddingProvider
from tailwag_memory.memory_context import PersonMemoryContextService, format_person_memory_markdown
from tailwag_memory.memory_items import (
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
    EpisodeMemoryExtractionService,
    MemoryConsolidationService,
    MemoryItemService,
    OpenAIMemoryConsolidationProvider,
    OpenAIMemoryExtractionProvider,
    followup_is_visible,
    stable_memory_id,
)
from tailwag_memory.models import EpisodeInput, MemoryItemInput, MemoryItemResult, PersonInput, PlaceInput


def _seed_row(episode_id: str) -> dict[str, object]:
    return {
        "episode_id": episode_id,
        "summary": f"Jamie mentioned robot demos in {episode_id}.",
        "transcript": f"Jamie: robot demos help me understand memory systems. ({episode_id})",
        "start_time": f"2026-06-1{episode_id[-1]}T10:00:00+00:00",
        "summary_embedding": [0.1] * 8,
    }


def _neighbor_row(episode_id: str) -> dict[str, object]:
    row = _seed_row(episode_id)
    row["score"] = 0.9
    return row


class MemoryItemServiceTest(unittest.TestCase):
    def test_upsert_item_writes_memory_item_relationships_and_embedding(self) -> None:
        runner = RecordingQueryRunner()
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        memory_id = service.upsert_item(
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

        self.assertEqual(
            memory_id,
            stable_memory_id(
                person_id="person_jamie",
                kind="preference",
                key="likes_robot_demos",
            ),
        )
        query = runner.queries[0]
        self.assertIn("MemoryItem", query.query)
        self.assertIn("HAS_MEMORY", query.query)
        self.assertIn("SUPPORTED_BY", query.query)
        self.assertEqual(query.parameters["person_id"], "person_jamie")
        self.assertEqual(query.parameters["episode_id"], "episode_1")
        self.assertEqual(len(query.parameters["summary_embedding"]), 8)

    def test_followup_requires_expires_at(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "expires_at"):
            service.upsert_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="followup",
                    key="cape_cod_trip",
                    summary="Cape Cod trip planned for the weekend.",
                    due_at="2026-06-22T09:00:00+00:00",
                ),
            )

    def test_memory_id_is_deterministic_by_person_kind_and_key(self) -> None:
        jamie_id = stable_memory_id(
            person_id="person_jamie",
            kind="preference",
            key="likes_robot_demos",
        )
        casey_id = stable_memory_id(
            person_id="person_casey",
            kind="preference",
            key="likes_robot_demos",
        )

        self.assertEqual(
            jamie_id,
            stable_memory_id(person_id="person_jamie", kind="preference", key="likes_robot_demos"),
        )
        self.assertNotEqual(jamie_id, casey_id)

    def test_rejects_caller_supplied_cross_person_memory_id(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "deterministic"):
            service.upsert_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    memory_id="mem_shared",
                    kind="fact",
                    key="robot_memory_project",
                    summary="working on robot social memory extraction",
                ),
            )

    def test_identity_owned_directory_summary_is_rejected(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "directory"):
            service.upsert_item(
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
            service.upsert_item(
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

        memory_id = service.upsert_item(
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
        self.assertIn("HAS_MEMORY", runner.queries[0].query)
        self.assertIn("vector.similarity.cosine", runner.queries[0].query)
        self.assertEqual(runner.queries[0].parameters["limit"], 3)

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

    def test_update_item_preserves_followup_window_and_metadata_by_default(self) -> None:
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
                        "source_ref": "segment_1",
                        "status": "active",
                        "due_at": "2026-06-22T09:00:00+00:00",
                        "expires_at": "2026-06-27T23:59:00+00:00",
                        "metadata_json": '{"destination":"Cape Cod"}',
                    }
                ],
                [{"memory_id": "mem_followup"}],
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        updated = service.update_item("mem_followup", summary="Cape Cod trip is still planned.")

        self.assertTrue(updated)
        params = runner.queries[1].parameters
        self.assertEqual(params["due_at"], "2026-06-22T09:00:00+00:00")
        self.assertEqual(params["expires_at"], "2026-06-27T23:59:00+00:00")
        self.assertIn("Cape Cod", params["metadata_json"])

    def test_update_item_treats_source_ref_none_as_empty_string(self) -> None:
        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_fact",
                        "person_id": "person_jamie",
                        "kind": "fact",
                        "key": "robot_memory",
                        "summary": "working on robot memory",
                        "source": "live_chat",
                        "source_ref": "segment_1",
                        "status": "active",
                    }
                ],
                [{"memory_id": "mem_fact"}],
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        self.assertTrue(service.update_item("mem_fact", source_ref=None))

        self.assertEqual(runner.queries[1].parameters["source_ref"], "")

    def test_rejects_invalid_observed_at(self) -> None:
        service = MemoryItemService(RecordingQueryRunner(), MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "observed_at"):
            service.upsert_item(
                person_id="person_jamie",
                item=MemoryItemInput(
                    kind="fact",
                    key="robot_memory",
                    summary="working on robot memory",
                    observed_at="not-a-time",
                ),
            )

    def test_update_item_rejects_clearing_active_followup_expiry(self) -> None:
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
                        "expires_at": "2026-06-27T23:59:00+00:00",
                    }
                ]
            ]
        )
        service = MemoryItemService(runner, MockOpenAIEmbeddingProvider(dimension=8))

        with self.assertRaisesRegex(ValueError, "expires_at"):
            service.update_item("mem_followup", expires_at="")

        self.assertEqual(len(runner.queries), 1)

    def test_candidate_items_prioritizes_pinned_context_then_lexical_and_vector(self) -> None:
        class CandidateService(MemoryItemService):
            def vector_search(self, **kwargs):
                self.vector_kwargs = kwargs
                return [
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
            limit=4,
        )

        self.assertEqual([item.memory_id for item in selected], ["mem_boundary", "mem_pref", "mem_lexical", "mem_vector"])
        self.assertEqual(service.vector_kwargs["person_id"], "person_jamie")


class MemoryConsolidationServiceTest(unittest.TestCase):
    def test_consolidation_uses_default_minimum_four_evidence_episodes(self) -> None:
        self.assertEqual(DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES, 4)

    def test_consolidate_person_creates_memory_with_four_valid_supporting_episodes(self) -> None:
        class FakeConsolidationProvider:
            def __init__(self) -> None:
                self.calls = []

            def consolidate(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "fact",
                            "key": "robot_memory_demos",
                            "summary": "uses hands-on robot demos to understand memory systems",
                            "supported_episode_ids": ["ep1", "ep2", "ep3", "ep4"],
                            "metadata": {},
                        }
                    ],
                }

        provider = FakeConsolidationProvider()
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
                [],
                [{"linked_count": 4}],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), provider)

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertTrue(result.provider_called)
        self.assertEqual(len(result.created_memory_ids), 1)
        self.assertEqual(result.skipped_ops, [])
        self.assertEqual(provider.calls[0]["min_evidence_episodes"], 4)
        self.assertEqual(
            [item["episode_id"] for item in provider.calls[0]["episode_clusters"][0]],
            ["ep1", "ep2", "ep3", "ep4"],
        )
        self.assertIn("db.index.vector.queryNodes('episode_summary_embedding'", runner.queries[1].query)
        memory_query = [query for query in runner.queries if "MERGE (m:MemoryItem" in query.query][-1]
        self.assertEqual(memory_query.parameters["source_ref"], "consolidation")
        link_query = runner.queries[-1]
        self.assertEqual(link_query.parameters["episode_ids"], ["ep1", "ep2", "ep3", "ep4"])
        self.assertIn("MERGE (m)-[:SUPPORTED_BY]->(e)", link_query.query)

    def test_consolidation_skips_operation_when_valid_evidence_drops_below_four(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "fact",
                            "key": "robot_memory_demos",
                            "summary": "uses robot demos to understand memory systems",
                            "supported_episode_ids": ["ep1", "ep2", "ep3", "ep_missing"],
                            "metadata": {},
                        }
                    ],
                }

        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertIn("unsupported_episode_id", {item["reason"] for item in result.skipped_ops})
        self.assertIn("insufficient_valid_evidence", {item["reason"] for item in result.skipped_ops})
        self.assertFalse(any("MERGE (m:MemoryItem" in query.query for query in runner.queries))

    def test_duplicate_supporting_episode_ids_count_once(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "fact",
                            "key": "robot_memory_demos",
                            "summary": "uses robot demos to understand memory systems",
                            "supported_episode_ids": ["ep1", "ep1", "ep2", "ep3"],
                            "metadata": {},
                        }
                    ],
                }

        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertEqual([item["reason"] for item in result.skipped_ops], ["insufficient_valid_evidence"])

    def test_consolidation_updates_only_known_candidate_memory_ids_and_links_support(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "update",
                            "memory_id": "mem_existing",
                            "summary": "uses robot demos to understand memory systems",
                            "supported_episode_ids": ["ep1", "ep2", "ep3", "ep4"],
                            "metadata": {},
                        },
                        {
                            "op": "archive",
                            "memory_id": "mem_missing",
                            "supported_episode_ids": ["ep1", "ep2", "ep3", "ep4"],
                            "metadata": {},
                        },
                    ],
                }

        existing = {
            "memory_id": "mem_existing",
            "person_id": "person_jamie",
            "kind": "fact",
            "key": "robot_memory_demos",
            "summary": "likes robot demos",
            "source": "live_chat",
            "status": "active",
        }
        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [existing],
                [existing],
                [{"memory_id": "mem_existing"}],
                [{"linked_count": 4}],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.updated_memory_ids, ["mem_existing"])
        self.assertEqual(result.archived_memory_ids, [])
        self.assertIn("unknown_memory_id", {item["reason"] for item in result.skipped_ops})
        self.assertEqual(runner.queries[-1].parameters["episode_ids"], ["ep1", "ep2", "ep3", "ep4"])

    def test_consolidation_rejects_nonempty_provider_metadata(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "fact",
                            "key": "robot_memory_demos",
                            "summary": "uses robot demos to understand memory systems",
                            "supported_episode_ids": ["ep1", "ep2", "ep3", "ep4"],
                            "metadata": {"extra": True},
                        }
                    ],
                }

        runner = RecordingQueryRunner(
            results=[
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

        result = service.consolidate_person("person_jamie", cluster_limit=1)

        self.assertEqual(result.created_memory_ids, [])
        self.assertIn("memory consolidation metadata must be empty", {item["reason"] for item in result.skipped_ops})
        self.assertFalse(any("MERGE (m:MemoryItem" in query.query for query in runner.queries))

    def test_consolidation_skips_provider_when_fewer_than_four_seed_episodes(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                raise AssertionError("provider should not be called")

        runner = RecordingQueryRunner(results=[[_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3")]])
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

        result = service.consolidate_person("person_jamie")

        self.assertFalse(result.provider_called)
        self.assertEqual(result.created_memory_ids, [])
        self.assertEqual(len(runner.queries), 1)

    def test_consolidate_all_isolates_per_person_errors(self) -> None:
        class FakeConsolidationProvider:
            def consolidate(self, **kwargs):
                raise RuntimeError("provider unavailable")

        runner = RecordingQueryRunner(
            results=[
                [{"person_id": "person_jamie"}],
                [_seed_row("ep1"), _seed_row("ep2"), _seed_row("ep3"), _seed_row("ep4")],
                [_neighbor_row("ep1"), _neighbor_row("ep2"), _neighbor_row("ep3"), _neighbor_row("ep4")],
                [],
            ]
        )
        service = MemoryConsolidationService(runner, MockOpenAIEmbeddingProvider(dimension=8), FakeConsolidationProvider())

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
                        "summary": "Jamie mentioned Luna had a vet visit tomorrow.",
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
        self.assertIn("- 2026-06-16: Jamie mentioned Luna had a vet visit tomorrow.", markdown)
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
                        "summary": "Jamie mentioned Luna had a vet visit tomorrow.",
                        "transcript": "Jamie: Luna has a vet visit tomorrow.",
                        "text": "Summary: Jamie mentioned Luna had a vet visit tomorrow.\nTranscript:\nJamie: Luna has a vet visit tomorrow.",
                        "start_time": "2026-06-16T14:00:00+00:00",
                    }
                ],
            ]
        )
        service = PersonMemoryContextService(runner)

        markdown = service.markdown_for_person(" person_jamie ", recent_episode_limit=2)

        self.assertIn("Recent Episodes:", markdown)
        self.assertIn("- 2026-06-16: Jamie mentioned Luna had a vet visit tomorrow.", markdown)
        self.assertEqual(runner.queries[1].parameters, {"person_id": "person_jamie", "limit": 2})
        self.assertIn("e.id AS episode_id", runner.queries[1].query)
        self.assertIn("'episode' AS item_type", runner.queries[1].query)


class EpisodeMemoryExtractionServiceTest(unittest.TestCase):
    def test_extract_for_episode_processes_all_participants_and_scopes_provider_calls(self) -> None:
        class FakeExtractionProvider:
            def __init__(self) -> None:
                self.calls = []

            def extract(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "preference",
                            "key": "likes_robot_demos",
                            "summary": "likes: hands-on robot demos",
                        }
                    ],
                }

        provider = FakeExtractionProvider()
        runner = RecordingQueryRunner(results=[[], [], [], [], [], []])
        service = EpisodeMemoryExtractionService(runner, MockOpenAIEmbeddingProvider(dimension=8), provider)
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            summary="Jamie and Casey discussed robot demos.",
            transcript="Jamie: I like robot demos.\nCasey: I prefer quiet greetings.",
            retention_class="standard",
            place=PlaceInput(building_code="MAIN", room_id="101"),
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

    def test_extract_for_stored_episode_defaults_to_speakers_and_falls_back_to_all(self) -> None:
        class FakeExtractionProvider:
            def __init__(self) -> None:
                self.people = []

            def extract(self, **kwargs):
                self.people.append(kwargs["person_id"])
                return {"update": False, "ops": []}

        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "id": "episode_1",
                        "episode_type": "conversation",
                        "start_time": "2026-06-18T10:00:00+00:00",
                        "summary": "Jamie spoke.",
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
        provider = FakeExtractionProvider()
        service = EpisodeMemoryExtractionService(runner, MockOpenAIEmbeddingProvider(dimension=8), provider)

        result = service.extract_for_stored_episode("episode_1")

        self.assertEqual([item.person_id for item in result.memory_results], ["person_jamie"])
        self.assertEqual(provider.people, ["person_jamie"])

    def test_extract_for_episode_returns_per_person_error_without_failing_episode(self) -> None:
        class FakeExtractionProvider:
            def extract(self, **kwargs):
                if kwargs["person_id"] == "person_casey":
                    raise RuntimeError("provider unavailable")
                return {"update": False, "ops": []}

        runner = RecordingQueryRunner(results=[[], []])
        service = EpisodeMemoryExtractionService(
            runner,
            MockOpenAIEmbeddingProvider(dimension=8),
            FakeExtractionProvider(),
        )
        episode = EpisodeInput(
            id="episode_1",
            episode_type="conversation",
            start_time="2026-06-18T10:00:00+00:00",
            end_time=None,
            summary="Jamie and Casey spoke.",
            transcript="Jamie: hello\nCasey: hello",
            retention_class="standard",
            place=PlaceInput(building_code="MAIN", room_id="101"),
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
        class FakeExtractionProvider:
            def __init__(self) -> None:
                self.calls = []

            def extract(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "preference",
                            "key": "likes_robot_demos",
                            "summary": "likes: hands-on robot demos",
                        }
                    ],
                }

        provider = FakeExtractionProvider()
        runner = RecordingQueryRunner(results=[[], [], []])
        service = EpisodeMemoryExtractionService(
            runner,
            MockOpenAIEmbeddingProvider(dimension=8),
            provider,
        )

        result = service.extract_for_episode(
            EpisodeInput(
                id="episode_segment_1",
                episode_type="conversation",
                start_time="2026-06-16T10:00:00+00:00",
                end_time=None,
                summary="Jamie likes hands-on robot demos.",
                transcript="Jamie: I like hands-on robot demos.",
                retention_class="standard",
                place=PlaceInput(building_code="MAIN", room_id="101"),
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
        memory_queries = [query for query in runner.queries if "MERGE (m:MemoryItem" in query.query]
        self.assertTrue(memory_queries)
        memory_params = memory_queries[-1].parameters
        self.assertEqual(memory_params["episode_id"], "episode_segment_1")
        self.assertEqual(memory_params["source"], "calling-system")
        self.assertEqual(memory_params["source_ref"], "episode_segment_1")
        self.assertEqual(memory_params["observed_at"], "2026-06-16T10:00:00+00:00")

    def test_extract_for_episode_reports_update_archive_and_skipped_operations(self) -> None:
        class FakeExtractionProvider:
            def extract(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "update",
                            "memory_id": "mem_existing",
                            "kind": "",
                            "key": "",
                            "summary": "updated robot demo preference",
                            "observed_at": "",
                            "due_at": "",
                            "expires_at": "",
                            "metadata": {},
                        },
                        {
                            "op": "archive",
                            "memory_id": "mem_existing",
                            "kind": "",
                            "key": "",
                            "summary": "",
                            "observed_at": "",
                            "due_at": "",
                            "expires_at": "",
                            "metadata": {},
                        },
                        {
                            "op": "archive",
                            "memory_id": "mem_unknown",
                            "kind": "",
                            "key": "",
                            "summary": "",
                            "observed_at": "",
                            "due_at": "",
                            "expires_at": "",
                            "metadata": {},
                        },
                        {"op": "bad-op"},
                        "not-a-dict",
                        {"op": "noop"},
                    ],
                }

        runner = RecordingQueryRunner(
            results=[
                [
                    {
                        "memory_id": "mem_existing",
                        "person_id": "person_jamie",
                        "kind": "preference",
                        "key": "likes_robot_demos",
                        "summary": "likes: robot demos",
                        "source": "live_chat",
                        "source_ref": "segment_old",
                        "status": "active",
                        "metadata_json": '{"origin":"old"}',
                    }
                ],
                [],
                [
                    {
                        "memory_id": "mem_existing",
                        "person_id": "person_jamie",
                        "kind": "preference",
                        "key": "likes_robot_demos",
                        "summary": "likes: robot demos",
                        "source": "live_chat",
                        "source_ref": "segment_old",
                        "status": "active",
                        "metadata_json": '{"origin":"old"}',
                    }
                ],
                [{"memory_id": "mem_existing"}],
                [{"memory_id": "mem_existing"}],
            ]
        )
        service = EpisodeMemoryExtractionService(
            runner,
            MockOpenAIEmbeddingProvider(dimension=8),
            FakeExtractionProvider(),
        )

        result = service.extract_for_episode(
            EpisodeInput(
                id="episode_segment_2",
                episode_type="conversation",
                start_time="2026-06-17T10:00:00+00:00",
                end_time=None,
                summary="Jamie still likes robot demos.",
                transcript="Jamie: I still like robot demos.",
                retention_class="standard",
                place=PlaceInput(building_code="MAIN", room_id="101"),
                participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
            )
        )

        person_result = result.memory_results[0]
        self.assertEqual(person_result.updated_memory_ids, ["mem_existing"])
        self.assertEqual(person_result.archived_memory_ids, ["mem_existing"])
        self.assertEqual(len(person_result.skipped_ops), 3)
        self.assertIn("unknown_memory_id", {item["reason"] for item in person_result.skipped_ops})

    def test_metadata_value_alias_is_not_accepted(self) -> None:
        class FakeExtractionProvider:
            def extract(self, **kwargs):
                return {
                    "update": True,
                    "ops": [
                        {
                            "op": "create",
                            "kind": "fact",
                            "key": "robot_memory",
                            "summary": "working on robot memory",
                            "value": {"legacy": True},
                        }
                    ],
                }

        runner = RecordingQueryRunner(results=[[], [], []])
        service = EpisodeMemoryExtractionService(
            runner,
            MockOpenAIEmbeddingProvider(dimension=8),
            FakeExtractionProvider(),
        )

        service.extract_for_episode(
            EpisodeInput(
                id="episode_segment_3",
                episode_type="conversation",
                start_time="2026-06-17T10:00:00+00:00",
                end_time=None,
                summary="Jamie works on robot memory.",
                transcript="Jamie: I work on robot memory.",
                retention_class="standard",
                place=PlaceInput(building_code="MAIN", room_id="101"),
                participants=[PersonInput(id="person_jamie", display_name="Jamie", role="speaker")],
            )
        )

        memory_queries = [query for query in runner.queries if "MERGE (m:MemoryItem" in query.query]
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
        self.assertIn("stay relevant for weeks at a time", developer_prompt)
        self.assertIn("Insignificant observations", developer_prompt)
        self.assertIn("future conversation more fruitful", developer_prompt)
        self.assertIn("bugs being debugged today", developer_prompt)
        self.assertIn("must be followup, not fact or preference", developer_prompt)
        self.assertIn("expire within a week", developer_prompt)


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
                        "summary": "Jamie likes robot demos.",
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
        self.assertIn("supported_episode_ids", op_schema["properties"])
        self.assertIn("supported_episode_ids", op_schema["required"])
        developer_prompt = client.responses.kwargs["input"][0]["content"]
        self.assertIn("Do not invent episode IDs", developer_prompt)
        self.assertIn("required minimum number", developer_prompt)
        user_payload = json.loads(client.responses.kwargs["input"][1]["content"])
        self.assertEqual(user_payload["min_evidence_episodes"], 4)
        self.assertEqual(user_payload["episode_clusters"][0][0]["episode_id"], "ep1")


if __name__ == "__main__":
    unittest.main()
