from __future__ import annotations

from typing import Any

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .memory_item_constants import (
    DEFAULT_CONSOLIDATION_CLUSTER_LIMIT,
    DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
    DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT,
    DEFAULT_CONSOLIDATION_SEED_LIMIT,
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
)
from .memory_item_helpers import (
    _EpisodeEvidence,
    _consolidation_metadata,
    _dedupe_episode_evidence,
    _episode_evidence_payload,
    _followup_expired_at_creation,
    _latest_episode_time,
    _positive_int,
    _row_to_episode_evidence,
    _unique_nonempty,
    _validated_support_ids,
    normalize_memory_source,
)
from .memory_item_protocols import MemoryConsolidationProvider
from .memory_item_service import MemoryItemService
from .models import (
    MemoryConsolidationResult,
    MemoryItemInput,
    MemoryItemResult,
    PersonMemoryConsolidationResult,
    utc_now_iso,
)
from .vector_queries import vector_search_clause


class MemoryConsolidationService:
    """Consolidate repeated per-person episode evidence into MemoryItems."""

    def __init__(
        self,
        runner: QueryRunner,
        embeddings: EmbeddingProvider,
        consolidation_provider: MemoryConsolidationProvider,
    ) -> None:
        """Store dependencies for consolidation operations."""
        self.runner = runner
        self.embeddings = embeddings
        self.consolidation_provider = consolidation_provider

    def consolidate_person(
        self,
        person_id: str,
        *,
        min_evidence_episodes: int = DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
        seed_limit: int = DEFAULT_CONSOLIDATION_SEED_LIMIT,
        neighbor_limit: int = DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT,
        cluster_limit: int = DEFAULT_CONSOLIDATION_CLUSTER_LIMIT,
        episode_text_limit: int = DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
    ) -> PersonMemoryConsolidationResult:
        """Run one per-person consolidation pass."""
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        minimum = _positive_int(min_evidence_episodes, DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES)
        clusters = self._episode_clusters_for_person(
            rendered_person_id,
            min_evidence_episodes=minimum,
            seed_limit=seed_limit,
            neighbor_limit=neighbor_limit,
            cluster_limit=cluster_limit,
        )
        candidate_episode_ids = _unique_nonempty(
            [episode.episode_id for cluster in clusters for episode in cluster]
        )
        if not clusters:
            return PersonMemoryConsolidationResult(
                person_id=rendered_person_id,
                candidate_episode_ids=candidate_episode_ids,
                provider_called=False,
            )

        memory_service = MemoryItemService(self.runner, self.embeddings)
        existing_memories = memory_service.list_active_items(person_id=rendered_person_id, limit=100)
        current_time = utc_now_iso()
        payload = self.consolidation_provider.consolidate(
            person_id=rendered_person_id,
            existing_memories=existing_memories,
            episode_clusters=[
                [_episode_evidence_payload(episode, text_limit=episode_text_limit) for episode in cluster]
                for cluster in clusters
            ],
            current_time=current_time,
            min_evidence_episodes=minimum,
        )
        applied = _apply_consolidation_operations(
            memory_service,
            person_id=rendered_person_id,
            operations=payload,
            source="calling-system",
            source_ref="consolidation",
            candidate_memories=existing_memories,
            evidence_by_id={
                episode.episode_id: episode for cluster in clusters for episode in cluster
            },
            min_evidence_episodes=minimum,
            processing_time=current_time,
        )
        return PersonMemoryConsolidationResult(
            person_id=rendered_person_id,
            update_requested=bool(isinstance(payload, dict) and payload.get("update")),
            created_memory_ids=applied["created"],
            superseded_memory_ids=applied["superseded"],
            skipped_ops=applied["skipped"],
            candidate_episode_ids=candidate_episode_ids,
            provider_called=True,
        )

    def consolidate_all(
        self,
        *,
        person_limit: int = 100,
        min_evidence_episodes: int = DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
        seed_limit: int = DEFAULT_CONSOLIDATION_SEED_LIMIT,
        neighbor_limit: int = DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT,
        cluster_limit: int = DEFAULT_CONSOLIDATION_CLUSTER_LIMIT,
        episode_text_limit: int = DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
    ) -> MemoryConsolidationResult:
        """Run consolidation for people with episode evidence."""
        results: list[PersonMemoryConsolidationResult] = []
        errors: list[dict[str, str]] = []
        for person_id in self._person_ids_with_episodes(limit=person_limit):
            try:
                result = self.consolidate_person(
                    person_id,
                    min_evidence_episodes=min_evidence_episodes,
                    seed_limit=seed_limit,
                    neighbor_limit=neighbor_limit,
                    cluster_limit=cluster_limit,
                    episode_text_limit=episode_text_limit,
                )
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                result = PersonMemoryConsolidationResult(person_id=person_id, error=error)
                errors.append({"person_id": person_id, "error": error})
            results.append(result)
        return MemoryConsolidationResult(person_results=results, memory_errors=errors)

    def _person_ids_with_episodes(self, *, limit: int) -> list[str]:
        """Return person IDs that have episode evidence."""
        rows = self.runner.run(
            """
            MATCH (p:Person)-[:PARTICIPATED_IN]->(:Episode)
            RETURN DISTINCT p.id AS person_id
            ORDER BY person_id
            LIMIT $limit
            """,
            {"limit": _positive_int(limit, 100)},
        )
        return [str(row.get("person_id") or "").strip() for row in rows if str(row.get("person_id") or "").strip()]

    def _episode_clusters_for_person(
        self,
        person_id: str,
        *,
        min_evidence_episodes: int,
        seed_limit: int,
        neighbor_limit: int,
        cluster_limit: int,
    ) -> list[list[_EpisodeEvidence]]:
        """Build person-scoped episode clusters using Neo4j vector search."""
        seeds = self._seed_episodes_for_person(person_id, limit=seed_limit)
        if len(seeds) < min_evidence_episodes:
            return []
        clusters: list[list[_EpisodeEvidence]] = []
        seen_cluster_keys: set[tuple[str, ...]] = set()
        for seed in seeds:
            if not isinstance(seed.get("transcript_embedding"), list):
                continue
            neighbors = self._neighbor_episodes_for_seed(
                person_id,
                embedding=seed["transcript_embedding"],
                limit=neighbor_limit,
            )
            cluster = _dedupe_episode_evidence([_row_to_episode_evidence(seed), *neighbors])
            cluster_ids = tuple(_unique_nonempty([episode.episode_id for episode in cluster]))
            if len(cluster_ids) < min_evidence_episodes or cluster_ids in seen_cluster_keys:
                continue
            clusters.append(cluster)
            seen_cluster_keys.add(cluster_ids)
            if len(clusters) >= _positive_int(cluster_limit, DEFAULT_CONSOLIDATION_CLUSTER_LIMIT):
                break
        return clusters

    def _seed_episodes_for_person(self, person_id: str, *, limit: int) -> list[dict[str, Any]]:
        """Fetch recent person episodes that can seed vector-neighbor search."""
        return self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:PARTICIPATED_IN]->(e:Episode)
            WHERE e.transcript_embedding IS NOT NULL
              AND coalesce(e.transcript, '') <> ''
            RETURN e.id AS episode_id,
                   e.transcript AS transcript,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   e.transcript_embedding AS transcript_embedding
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"person_id": person_id, "limit": _positive_int(limit, DEFAULT_CONSOLIDATION_SEED_LIMIT)},
        )

    def _neighbor_episodes_for_seed(
        self,
        person_id: str,
        *,
        embedding: list[float],
        limit: int,
    ) -> list[_EpisodeEvidence]:
        """Return vector-neighbor episodes that are linked to the same person."""
        rows = self.runner.run(
            vector_search_clause("episode_transcript_embedding", "node", "limit")
            + """
            MATCH (:Person {id: $person_id})-[:PARTICIPATED_IN]->(node)
            WHERE coalesce(node.transcript, '') <> ''
            RETURN node.id AS episode_id,
                   node.transcript AS transcript,
                   node.start_time AS start_time,
                   node.end_time AS end_time,
                   score AS score
            ORDER BY score DESC, node.start_time DESC
            """,
            {
                "person_id": person_id,
                "embedding": embedding,
                "limit": _positive_int(limit, DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT),
            },
        )
        episodes: list[_EpisodeEvidence] = []
        seen: set[str] = set()
        for row in rows:
            episode_id = str(row.get("episode_id") or "").strip()
            if not episode_id or episode_id in seen:
                continue
            episodes.append(_row_to_episode_evidence(row))
            seen.add(episode_id)
        return episodes


def _apply_consolidation_operations(
    memory_service: MemoryItemService,
    *,
    person_id: str,
    operations: dict[str, Any],
    source: str,
    source_ref: str,
    candidate_memories: list[MemoryItemResult],
    evidence_by_id: dict[str, _EpisodeEvidence],
    min_evidence_episodes: int,
    processing_time: str | None = None,
) -> dict[str, list[Any]]:
    """Apply provider consolidation operations after validating evidence IDs."""
    applied: dict[str, list[Any]] = {
        "created": [],
        "superseded": [],
        "skipped": [],
    }
    if not isinstance(operations, dict) or not operations.get("update"):
        return applied
    candidate_by_id = {item.memory_id: item for item in candidate_memories}
    for raw in operations.get("ops", []) or []:
        if not isinstance(raw, dict):
            applied["skipped"].append({"reason": "invalid_op", "op": raw})
            continue
        op = str(raw.get("op") or "").strip().casefold()
        if op == "noop":
            continue
        support = _validated_support_ids(raw, evidence_by_id=evidence_by_id, skipped=applied["skipped"])
        if len(support) < min_evidence_episodes:
            applied["skipped"].append({"reason": "insufficient_valid_evidence", "op": raw})
            continue
        observed_at = str(raw.get("observed_at") or "").strip() or _latest_episode_time(support, evidence_by_id)
        if op == "create":
            try:
                metadata = _consolidation_metadata(raw, default={})
                kind = str(raw.get("kind") or "")
                expires_at = str(raw.get("expires_at") or "")
                if _followup_expired_at_creation(
                    kind=kind,
                    expires_at=expires_at,
                    now=processing_time,
                ):
                    applied["skipped"].append({"reason": "followup_already_expired", "op": raw})
                    continue
                memory_id = memory_service.create_item(
                    person_id=person_id,
                    item=MemoryItemInput(
                        kind=kind,
                        key=str(raw.get("key") or ""),
                        summary=str(raw.get("summary") or ""),
                        source=normalize_memory_source(source),
                        source_ref=source_ref,
                        observed_at=observed_at,
                        due_at=str(raw.get("due_at") or ""),
                        expires_at=expires_at,
                        metadata=metadata,
                    ),
                )
                memory_service.link_supported_episodes(memory_id, support)
                applied["created"].append(memory_id)
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
            continue
        if op == "merge":
            raw_memory_ids = raw.get("memory_ids")
            if not isinstance(raw_memory_ids, list):
                applied["skipped"].append({"reason": "missing_memory_ids", "op": raw})
                continue
            source_memory_ids = _unique_nonempty([str(value or "") for value in raw_memory_ids])
            unknown_memory_ids = [memory_id for memory_id in source_memory_ids if memory_id not in candidate_by_id]
            for memory_id in unknown_memory_ids:
                applied["skipped"].append({"reason": "unknown_memory_id", "memory_id": memory_id, "op": raw})
            valid_source_memory_ids = [memory_id for memory_id in source_memory_ids if memory_id in candidate_by_id]
            if not valid_source_memory_ids:
                applied["skipped"].append({"reason": "no_valid_source_memory_ids", "op": raw})
                continue
            try:
                metadata = _consolidation_metadata(raw, default={})
                kind = str(raw.get("kind") or "")
                expires_at = str(raw.get("expires_at") or "")
                if _followup_expired_at_creation(
                    kind=kind,
                    expires_at=expires_at,
                    now=processing_time,
                ):
                    applied["skipped"].append({"reason": "followup_already_expired", "op": raw})
                    continue
                merge_result = memory_service.merge_items(
                    person_id=person_id,
                    merged_item=MemoryItemInput(
                        kind=kind,
                        key=str(raw.get("key") or ""),
                        summary=str(raw.get("summary") or ""),
                        source=normalize_memory_source(source),
                        source_ref=source_ref,
                        observed_at=observed_at,
                        due_at=str(raw.get("due_at") or ""),
                        expires_at=expires_at,
                        metadata=metadata,
                    ),
                    source_memory_ids=valid_source_memory_ids,
                    supported_by_episode_ids=support,
                )
                applied["created"].append(merge_result.merged_memory_id)
                applied["superseded"].extend(merge_result.superseded_memory_ids)
                for skipped_id in merge_result.skipped_source_memory_ids:
                    applied["skipped"].append({"reason": "invalid_source_memory_id", "memory_id": skipped_id, "op": raw})
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
            continue
        applied["skipped"].append({"reason": "unknown_operation", "op": raw})
    return applied
