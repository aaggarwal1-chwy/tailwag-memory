from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .memory_item_constants import PINNED_MEMORY_KEYS
from .memory_item_helpers import (
    _PRESERVE,
    _is_expired,
    _json_dumps,
    _json_loads,
    _tokenize,
    _unique_nonempty,
    _validate_item,
    _validate_update_fields,
    stable_memory_id,
)
from .models import MemoryItemInput, MemoryItemMergeResult, MemoryItemResult, utc_now_iso
from .vector_queries import vector_search_clause


class MemoryItemService:
    """Persist and retrieve durable person memory items."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        """Store dependencies for memory item operations."""
        self.runner = runner
        self.embeddings = embeddings

    def upsert_item(
        self,
        *,
        person_id: str,
        item: MemoryItemInput,
        supported_by_episode_id: str | None = None,
    ) -> str:
        """Create or replace one deterministic memory item."""
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        validated = _validate_item(item)
        expected_memory_id = stable_memory_id(
            person_id=rendered_person_id,
            kind=validated.kind,
            key=validated.key,
        )
        memory_id = (validated.memory_id or expected_memory_id).strip()
        if memory_id != expected_memory_id:
            raise ValueError("memory_id must be the deterministic person/kind/key memory id")
        now = utc_now_iso()
        observed_at = validated.observed_at or now
        self.runner.run(
            """
            MERGE (p:Person {id: $person_id})
            MERGE (m:MemoryItem {id: $memory_id})
            SET m.kind = $kind,
                m.key = $key,
                m.summary = $summary,
                m.summary_embedding = $summary_embedding,
                m.source = $source,
                m.source_ref = $source_ref,
                m.status = $status,
                m.observed_at = $observed_at,
                m.due_at = $due_at,
                m.expires_at = $expires_at,
                m.metadata_json = $metadata_json,
                m.created_at = coalesce(m.created_at, $now),
                m.updated_at = $now
            MERGE (p)-[:HAS_MEMORY]->(m)
            WITH m
            OPTIONAL MATCH (e:Episode {id: $episode_id})
            FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
              MERGE (m)-[:SUPPORTED_BY]->(e)
            )
            """,
            {
                "person_id": rendered_person_id,
                "memory_id": memory_id,
                "kind": validated.kind,
                "key": validated.key,
                "summary": validated.summary,
                "summary_embedding": self.embeddings.embed(validated.summary),
                "source": validated.source,
                "source_ref": validated.source_ref,
                "status": validated.status,
                "observed_at": observed_at,
                "due_at": validated.due_at,
                "expires_at": validated.expires_at,
                "metadata_json": _json_dumps(validated.metadata),
                "now": now,
                "episode_id": str(supported_by_episode_id or "").strip() or None,
            },
        )
        return memory_id

    def update_item(
        self,
        memory_id: str,
        *,
        summary: str = "",
        source_ref: str | None | object = _PRESERVE,
        status: str | object = _PRESERVE,
        observed_at: str = "",
        due_at: str | object = _PRESERVE,
        expires_at: str | object = _PRESERVE,
        metadata: dict[str, Any] | object = _PRESERVE,
        supported_by_episode_id: str | None = None,
    ) -> bool:
        """Update an existing memory item when it exists."""
        rendered = str(memory_id or "").strip()
        if not rendered:
            return False
        existing = self.get_item(rendered)
        if existing is None:
            return False
        next_summary = str(summary or "").strip() or existing.summary
        if source_ref is _PRESERVE:
            next_source_ref = existing.source_ref
        elif source_ref is None:
            next_source_ref = ""
        else:
            next_source_ref = str(source_ref).strip()
        next_status = str(status).strip() if status is not _PRESERVE else existing.status
        next_due_at = str(due_at).strip() if due_at is not _PRESERVE else existing.due_at
        next_expires_at = str(expires_at).strip() if expires_at is not _PRESERVE else existing.expires_at
        next_observed_at = str(observed_at or "").strip()
        next_metadata = dict(metadata) if isinstance(metadata, dict) else existing.metadata
        item = MemoryItemInput(
            kind=existing.kind,
            key=existing.key,
            summary=next_summary,
            status=next_status,
            observed_at=next_observed_at,
            due_at=next_due_at,
            expires_at=next_expires_at,
            metadata=next_metadata,
        )
        _validate_update_fields(item)
        rows = self.runner.run(
            """
            MATCH (m:MemoryItem {id: $memory_id})
            SET m.summary = $summary,
                m.summary_embedding = $summary_embedding,
                m.source_ref = $source_ref,
                m.status = $status,
                m.observed_at = coalesce($observed_at, m.observed_at),
                m.due_at = $due_at,
                m.expires_at = $expires_at,
                m.metadata_json = $metadata_json,
                m.updated_at = $now
            WITH m
            OPTIONAL MATCH (e:Episode {id: $episode_id})
            FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
              MERGE (m)-[:SUPPORTED_BY]->(e)
            )
            RETURN m.id AS memory_id
            """,
            {
                "memory_id": rendered,
                "summary": next_summary,
                "summary_embedding": self.embeddings.embed(next_summary),
                "source_ref": next_source_ref,
                "status": next_status,
                "observed_at": next_observed_at or None,
                "due_at": next_due_at,
                "expires_at": next_expires_at,
                "metadata_json": _json_dumps(next_metadata),
                "now": utc_now_iso(),
                "episode_id": str(supported_by_episode_id or "").strip() or None,
            },
        )
        return bool(rows)

    def archive_item(self, memory_id: str) -> bool:
        """Archive a memory item by id."""
        rendered = str(memory_id or "").strip()
        if not rendered:
            return False
        rows = self.runner.run(
            """
            MATCH (m:MemoryItem {id: $memory_id})
            SET m.status = 'archived',
                m.updated_at = $now
            RETURN m.id AS memory_id
            """,
            {"memory_id": rendered, "now": utc_now_iso()},
        )
        return bool(rows)

    def link_supported_episodes(self, memory_id: str, episode_ids: list[str]) -> int:
        """Link a memory item to distinct supporting episodes that already exist."""
        rendered = str(memory_id or "").strip()
        unique_episode_ids = _unique_nonempty(episode_ids)
        if not rendered or not unique_episode_ids:
            return 0
        rows = self.runner.run(
            """
            MATCH (m:MemoryItem {id: $memory_id})
            UNWIND $episode_ids AS episode_id
            MATCH (e:Episode {id: episode_id})
            MERGE (m)-[:SUPPORTED_BY]->(e)
            RETURN count(DISTINCT e.id) AS linked_count
            """,
            {"memory_id": rendered, "episode_ids": unique_episode_ids},
        )
        if rows and isinstance(rows[0].get("linked_count"), int):
            return int(rows[0]["linked_count"])
        return len(unique_episode_ids)

    def merge_items(
        self,
        *,
        person_id: str,
        merged_item: MemoryItemInput,
        source_memory_ids: list[str],
        supported_by_episode_ids: list[str] | None = None,
        merged_memory_id: str | None = None,
    ) -> MemoryItemMergeResult:
        """Merge related person memories into one active memory item."""
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        source_ids = _unique_nonempty(source_memory_ids)
        if not source_ids:
            raise ValueError("source_memory_ids is required")

        validated = _validate_item(merged_item)
        rendered_merged_id = str(merged_memory_id or "").strip()
        if rendered_merged_id:
            valid_merged_ids = self._visible_memory_ids_for_person(
                rendered_person_id,
                [rendered_merged_id],
            )
            if rendered_merged_id not in valid_merged_ids:
                raise ValueError("merged_memory_id must be an active memory for person")

        valid_source_ids = self._visible_memory_ids_for_person(rendered_person_id, source_ids)
        valid_source_set = set(valid_source_ids)
        skipped_source_ids = [memory_id for memory_id in source_ids if memory_id not in valid_source_set]
        if not valid_source_ids:
            raise ValueError("at least one source memory must be visible for person")

        if rendered_merged_id:
            self.update_item(
                rendered_merged_id,
                summary=validated.summary,
                source_ref=validated.source_ref,
                status="active",
                observed_at=validated.observed_at,
                due_at=validated.due_at,
                expires_at=validated.expires_at,
                metadata=validated.metadata,
            )
        else:
            rendered_merged_id = self.upsert_item(person_id=rendered_person_id, item=validated)

        redundant_source_ids = [memory_id for memory_id in valid_source_ids if memory_id != rendered_merged_id]

        copied_count = self._copy_supported_episodes(
            person_id=rendered_person_id,
            merged_memory_id=rendered_merged_id,
            source_memory_ids=redundant_source_ids,
        )
        linked_count = self.link_supported_episodes(
            rendered_merged_id,
            list(supported_by_episode_ids or []),
        )
        superseded_ids = self._mark_superseded(
            person_id=rendered_person_id,
            merged_memory_id=rendered_merged_id,
            source_memory_ids=redundant_source_ids,
        )
        return MemoryItemMergeResult(
            person_id=rendered_person_id,
            merged_memory_id=rendered_merged_id,
            superseded_memory_ids=superseded_ids,
            linked_episode_count=copied_count + linked_count,
            skipped_source_memory_ids=skipped_source_ids,
        )

    def get_item(self, memory_id: str) -> MemoryItemResult | None:
        """Return one memory item by id when present."""
        rows = self.runner.run(
            """
            MATCH (p:Person)-[:HAS_MEMORY]->(m:MemoryItem {id: $memory_id})
            WHERE coalesce(m.status, 'active') <> 'superseded'
              AND NOT EXISTS { MATCH (m)-[:SUPERSEDED_BY]->(:MemoryItem) }
            RETURN p.id AS person_id,
                   m.id AS memory_id,
                   m.kind AS kind,
                   m.key AS key,
                   m.summary AS summary,
                   m.source AS source,
                   m.source_ref AS source_ref,
                   m.status AS status,
                   m.observed_at AS observed_at,
                   m.created_at AS created_at,
                   m.updated_at AS updated_at,
                   m.due_at AS due_at,
                   m.expires_at AS expires_at,
                   m.metadata_json AS metadata_json
            LIMIT 1
            """,
            {"memory_id": str(memory_id or "").strip()},
        )
        return self._row_to_item(rows[0]) if rows else None

    def list_items(
        self,
        *,
        person_id: str,
        kinds: tuple[str, ...] = (),
        statuses: tuple[str, ...] = (),
        source: str = "",
        limit: int = 100,
    ) -> list[MemoryItemResult]:
        """Return memory items matching basic filters."""
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE (size($kinds) = 0 OR m.kind IN $kinds)
              AND (size($statuses) = 0 OR m.status IN $statuses)
              AND ($source = '' OR m.source = $source)
              AND coalesce(m.status, 'active') <> 'superseded'
              AND NOT EXISTS { MATCH (m)-[:SUPERSEDED_BY]->(:MemoryItem) }
            RETURN $person_id AS person_id,
                   m.id AS memory_id,
                   m.kind AS kind,
                   m.key AS key,
                   m.summary AS summary,
                   m.source AS source,
                   m.source_ref AS source_ref,
                   m.status AS status,
                   m.observed_at AS observed_at,
                   m.created_at AS created_at,
                   m.updated_at AS updated_at,
                   m.due_at AS due_at,
                   m.expires_at AS expires_at,
                   m.metadata_json AS metadata_json
            ORDER BY m.observed_at DESC, m.updated_at DESC
            LIMIT $limit
            """,
            {
                "person_id": str(person_id or "").strip(),
                "kinds": list(kinds),
                "statuses": list(statuses),
                "source": str(source or "").strip(),
                "limit": max(1, int(limit or 100)),
            },
        )
        return [self._row_to_item(row) for row in rows]

    def list_active_items(
        self,
        *,
        person_id: str,
        kinds: tuple[str, ...] = (),
        source: str = "",
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryItemResult]:
        """Return active, unexpired memory items."""
        requested_limit = max(1, int(limit or 100))
        items = self.list_items(
            person_id=person_id,
            kinds=kinds,
            statuses=("active",),
            source=source,
            limit=max(requested_limit * 5, 100),
        )
        return [item for item in items if not _is_expired(item, now=now)][:requested_limit]

    def vector_search(
        self,
        *,
        person_id: str,
        text: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[MemoryItemResult]:
        """Return active memory items ranked by summary similarity."""
        requested_limit = max(1, int(limit or 10))
        candidate_limit = max(requested_limit * 5, 25)
        rows = self.runner.run(
            vector_search_clause("memory_item_summary_embedding", "node", "candidate_limit")
            + """
            MATCH (:Person {id: $person_id})-[:HAS_MEMORY]->(node)
            WHERE node.status = 'active'
              AND NOT EXISTS { MATCH (node)-[:SUPERSEDED_BY]->(:MemoryItem) }
            RETURN $person_id AS person_id,
                   node.id AS memory_id,
                   node.kind AS kind,
                   node.key AS key,
                   node.summary AS summary,
                   node.source AS source,
                   node.source_ref AS source_ref,
                   node.status AS status,
                   node.observed_at AS observed_at,
                   node.created_at AS created_at,
                   node.updated_at AS updated_at,
                   node.due_at AS due_at,
                   node.expires_at AS expires_at,
                   node.metadata_json AS metadata_json,
                   score AS score
            ORDER BY score DESC
            LIMIT $candidate_limit
            """,
            {
                "embedding": self.embeddings.embed(text),
                "person_id": str(person_id or "").strip(),
                "candidate_limit": candidate_limit,
            },
        )
        items = [item for item in (self._row_to_item(row) for row in rows) if not _is_expired(item, now=now)]
        return items[:requested_limit]

    def candidate_items(
        self,
        *,
        person_id: str,
        transcript: str,
        limit: int = 12,
    ) -> list[MemoryItemResult]:
        """Return existing memories relevant to a transcript."""
        active = self.list_active_items(person_id=person_id, limit=100)
        selected: list[MemoryItemResult] = []
        seen: set[str] = set()

        def add(item: MemoryItemResult) -> None:
            """Append an unseen candidate until the limit is reached."""
            if item.memory_id in seen or len(selected) >= max(1, limit):
                return
            selected.append(item)
            seen.add(item.memory_id)

        for item in active:
            if item.key in PINNED_MEMORY_KEYS or item.kind in {"boundary", "pet", "followup"}:
                add(item)

        if len(selected) >= max(1, limit):
            return selected

        transcript_tokens = _tokenize(transcript)
        scored: list[tuple[int, str, MemoryItemResult]] = []
        for item in active:
            if item.memory_id in seen:
                continue
            score = len(transcript_tokens & _tokenize(" ".join([item.kind, item.key, item.summary])))
            if score:
                scored.append((score, item.observed_at, item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        for _, _, item in scored:
            add(item)

        if len(selected) < max(1, limit) and transcript.strip():
            for item in self.vector_search(person_id=person_id, text=transcript, limit=limit):
                add(item)

        return selected

    def _visible_memory_ids_for_person(self, person_id: str, memory_ids: list[str]) -> list[str]:
        """Return non-superseded memory IDs owned by a person."""
        unique_ids = _unique_nonempty(memory_ids)
        if not unique_ids:
            return []
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE m.id IN $memory_ids
              AND coalesce(m.status, 'active') <> 'superseded'
              AND NOT EXISTS { MATCH (m)-[:SUPERSEDED_BY]->(:MemoryItem) }
            RETURN m.id AS memory_id
            """,
            {"person_id": person_id, "memory_ids": unique_ids},
        )
        found = {str(row.get("memory_id") or "").strip() for row in rows}
        return [memory_id for memory_id in unique_ids if memory_id in found]

    def _copy_supported_episodes(
        self,
        *,
        person_id: str,
        merged_memory_id: str,
        source_memory_ids: list[str],
    ) -> int:
        """Copy support episode links from source memories to a merged memory."""
        source_ids = _unique_nonempty(source_memory_ids)
        if not source_ids:
            return 0
        rows = self.runner.run(
            """
            MATCH (p:Person {id: $person_id})-[:HAS_MEMORY]->(merged:MemoryItem {id: $merged_memory_id})
            MATCH (p)-[:HAS_MEMORY]->(source:MemoryItem)
            WHERE source.id IN $source_memory_ids
              AND source.id <> merged.id
              AND coalesce(source.status, 'active') <> 'superseded'
              AND NOT EXISTS { MATCH (source)-[:SUPERSEDED_BY]->(:MemoryItem) }
            MATCH (source)-[:SUPPORTED_BY]->(episode:Episode)
            MERGE (merged)-[:SUPPORTED_BY]->(episode)
            RETURN count(DISTINCT episode.id) AS linked_count
            """,
            {
                "person_id": person_id,
                "merged_memory_id": merged_memory_id,
                "source_memory_ids": source_ids,
            },
        )
        if rows and isinstance(rows[0].get("linked_count"), int):
            return int(rows[0]["linked_count"])
        return 0

    def _mark_superseded(
        self,
        *,
        person_id: str,
        merged_memory_id: str,
        source_memory_ids: list[str],
    ) -> list[str]:
        """Mark source memories as superseded by a merged memory."""
        source_ids = _unique_nonempty(source_memory_ids)
        if not source_ids:
            return []
        rows = self.runner.run(
            """
            MATCH (p:Person {id: $person_id})-[:HAS_MEMORY]->(merged:MemoryItem {id: $merged_memory_id})
            MATCH (p)-[:HAS_MEMORY]->(source:MemoryItem)
            WHERE source.id IN $source_memory_ids
              AND source.id <> merged.id
              AND coalesce(source.status, 'active') <> 'superseded'
              AND NOT EXISTS { MATCH (source)-[:SUPERSEDED_BY]->(:MemoryItem) }
            SET source.status = 'superseded',
                source.updated_at = $now
            MERGE (source)-[:SUPERSEDED_BY]->(merged)
            RETURN source.id AS memory_id
            ORDER BY source.id
            """,
            {
                "person_id": person_id,
                "merged_memory_id": merged_memory_id,
                "source_memory_ids": source_ids,
                "now": utc_now_iso(),
            },
        )
        superseded = {str(row.get("memory_id") or "").strip() for row in rows}
        return [memory_id for memory_id in source_ids if memory_id in superseded]

    def _row_to_item(self, row: dict[str, Any]) -> MemoryItemResult:
        """Convert a Neo4j row into a memory item result."""
        return MemoryItemResult(
            memory_id=str(row["memory_id"]),
            person_id=str(row.get("person_id") or ""),
            kind=str(row.get("kind") or ""),
            key=str(row.get("key") or ""),
            summary=str(row.get("summary") or ""),
            source=str(row.get("source") or ""),
            source_ref=str(row.get("source_ref") or ""),
            status=str(row.get("status") or "active"),
            observed_at=str(row.get("observed_at") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            due_at=str(row.get("due_at") or ""),
            expires_at=str(row.get("expires_at") or ""),
            metadata=_json_loads(row.get("metadata_json")),
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )
