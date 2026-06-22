from __future__ import annotations

import re

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .models import (
    EpisodeMemoryResult,
    EventResult,
    PersonContextItem,
    PersonContextSource,
    PersonContextTranscriptLine,
    PersonRecognitionResult,
    SearchQuery,
)


_TRANSCRIPT_LINE_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s+(?P<speaker>[^:]+):\s*(?P<text>.*)$")
_VECTOR_INDEX_LABELS = {
    "episode_summary_embedding": "Episode",
    "episode_transcript_embedding": "Episode",
    "person_face_embedding": "Person",
    "person_audio_embedding": "Person",
    "memory_item_summary_embedding": "MemoryItem",
}


def _vector_search_clause(index_name: str, variable: str, limit_parameter: str) -> str:
    """Return a Neo4j vector search clause for a known index."""
    label = _VECTOR_INDEX_LABELS.get(index_name)
    if label is None:
        raise ValueError(f"unsupported vector index: {index_name}")
    return f"""
            CALL db.index.vector.queryNodes('{index_name}', ${limit_parameter}, $embedding)
            YIELD node AS {variable}, score
            WHERE {variable}:{label}
            """


def recent_episode_rows_for_person(runner: QueryRunner, person_id: str, limit: int) -> list[dict[str, object]]:
    """Fetch recent episode rows linked to a person."""
    return runner.run(
        """
            MATCH (:Person {id: $person_id})-[r:PARTICIPATED_IN]->(e:Episode)
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            RETURN e.id AS episode_id,
                   e.id AS item_id,
                   'episode' AS item_type,
                   e.summary AS summary,
                   e.transcript AS transcript,
                   ('Summary: ' + coalesce(e.summary, '') + '\nTranscript:\n' + coalesce(e.transcript, '')) AS text,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.role AS role,
                   r.source AS source
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
        {"person_id": person_id, "limit": limit},
    )


class EpisodeRetrievalService:
    """Read episode memories by person, place, or semantic match."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        """Store dependencies for episode retrieval."""
        self.runner = runner
        self.embeddings = embeddings

    def by_person(self, person_id: str, limit: int = 10) -> list[EpisodeMemoryResult]:
        """Return recent episode memories for a person."""
        rows = recent_episode_rows_for_person(self.runner, person_id, limit)
        return [self._row_to_result(row) for row in rows]

    def by_place(self, building_code: str, room_id: str, limit: int = 10) -> list[EpisodeMemoryResult]:
        """Return recent episode memories for a place."""
        rows = self.runner.run(
            """
            MATCH (e:Episode)-[:OCCURRED_AT]->(:Place {
              building_code: $building_code,
              room_id: $room_id
            })
            RETURN e.id AS episode_id,
                   e.summary AS summary,
                   e.transcript AS transcript
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"building_code": building_code, "room_id": room_id, "limit": limit},
        )
        return [self._row_to_result(row) for row in rows]

    def vector_search(self, text: str, target: str = "summary", limit: int = 10) -> list[EpisodeMemoryResult]:
        """Return episode memories ranked by vector similarity."""
        index_name = self._index_name(target)
        rows = self.runner.run(
            _vector_search_clause(index_name, "node", "limit")
            + """
            RETURN node.id AS episode_id,
                   node.summary AS summary,
                   node.transcript AS transcript,
                   score AS score
            ORDER BY score DESC
            """,
            {
                "limit": limit,
                "embedding": self.embeddings.embed(text),
            },
        )
        return [self._row_to_result(row) for row in rows]

    def hybrid_search(self, query: SearchQuery) -> list[EpisodeMemoryResult]:
        """Return vector-ranked episodes filtered by query constraints."""
        index_name = self._index_name(query.target)
        candidate_limit = max(query.limit * 5, 25)
        rows = self.runner.run(
            _vector_search_clause(index_name, "node", "candidate_limit")
            + """
            OPTIONAL MATCH (person:Person)-[:PARTICIPATED_IN]->(node)
            OPTIONAL MATCH (node)-[:OCCURRED_AT]->(place:Place)
            WITH node, score, collect(DISTINCT person.id) AS person_ids, collect(DISTINCT place) AS places
            WHERE ($person_id IS NULL OR $person_id IN person_ids)
              AND (
                $building_code IS NULL
                OR any(place IN places WHERE place.building_code = $building_code AND ($room_id IS NULL OR place.room_id = $room_id))
              )
              AND (
                $room_id IS NULL
                OR any(place IN places WHERE place.room_id = $room_id AND ($building_code IS NULL OR place.building_code = $building_code))
              )
            RETURN node.id AS episode_id,
                   node.summary AS summary,
                   node.transcript AS transcript,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {
                "candidate_limit": candidate_limit,
                "limit": query.limit,
                "embedding": self.embeddings.embed(query.text),
                "person_id": query.person_id,
                "building_code": query.building_code,
                "room_id": query.room_id,
            },
        )
        return [self._row_to_result(row) for row in rows]

    def _index_name(self, target: str) -> str:
        """Map an episode vector target to its index name."""
        if target == "summary":
            return "episode_summary_embedding"
        if target == "transcript":
            return "episode_transcript_embedding"
        raise ValueError("target must be 'summary' or 'transcript'")

    def _row_to_result(self, row: dict[str, object]) -> EpisodeMemoryResult:
        """Convert a Neo4j episode row into a result model."""
        return EpisodeMemoryResult(
            episode_id=str(row["episode_id"]),
            summary=str(row.get("summary") or ""),
            transcript=str(row.get("transcript") or ""),
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )


class PersonRecognitionService:
    """Read consented people by biometric vector similarity."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store dependencies for person recognition."""
        self.runner = runner

    def by_face_embedding(self, embedding: list[float], limit: int = 10) -> list[PersonRecognitionResult]:
        """Return consented people ranked by face embedding."""
        return self._vector_search("person_face_embedding", embedding, limit)

    def by_audio_embedding(self, embedding: list[float], limit: int = 10) -> list[PersonRecognitionResult]:
        """Return consented people ranked by audio embedding."""
        return self._vector_search("person_audio_embedding", embedding, limit)

    def _vector_search(
        self,
        index_name: str,
        embedding: list[float],
        limit: int,
    ) -> list[PersonRecognitionResult]:
        """Run a consent-filtered person vector search."""
        rows = self.runner.run(
            _vector_search_clause(index_name, "node", "candidate_limit")
            + """
            WHERE node.consent_status = 'consented'
              AND coalesce(node.status, 'active') <> 'archived'
            RETURN node.id AS person_id,
                   node.display_name AS display_name,
                   node.consent_status AS consent_status,
                   node.last_seen AS last_seen,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {
                "candidate_limit": max(limit * 5, 25),
                "limit": limit,
                "embedding": embedding,
            },
        )
        return [self._row_to_result(row) for row in rows]

    def _row_to_result(self, row: dict[str, object]) -> PersonRecognitionResult:
        """Convert a Neo4j person row into a recognition result."""
        return PersonRecognitionResult(
            person_id=str(row["person_id"]),
            display_name=str(row.get("display_name") or ""),
            consent_status=str(row.get("consent_status") or ""),
            last_seen=str(row["last_seen"]) if row.get("last_seen") is not None else None,
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )


class EventRetrievalService:
    """Read event memories by place."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store dependencies for event retrieval."""
        self.runner = runner

    def by_place(self, building_code: str, room_id: str, limit: int = 10) -> list[EventResult]:
        """Return recent events for a place."""
        rows = self.runner.run(
            """
            MATCH (e:Event)-[:OCCURRED_AT]->(p:Place {
              building_code: $building_code,
              room_id: $room_id
            })
            RETURN e.id AS event_id,
                   e.description AS description,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   p.building_code AS building_code,
                   p.room_id AS room_id
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"building_code": building_code, "room_id": room_id, "limit": limit},
        )
        return [self._row_to_result(row) for row in rows]

    def _row_to_result(self, row: dict[str, object]) -> EventResult:
        """Convert a Neo4j event row into a result model."""
        return EventResult(
            event_id=str(row["event_id"]),
            description=str(row.get("description") or ""),
            start_time=str(row.get("start_time") or ""),
            end_time=str(row["end_time"]) if row.get("end_time") is not None else None,
            building_code=str(row.get("building_code") or ""),
            room_id=str(row.get("room_id") or ""),
        )


class PersonContextRetrievalService:
    """Read person context from episodes and events."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider | None = None) -> None:
        """Store dependencies for person context retrieval."""
        self.runner = runner
        self.embeddings = embeddings

    def source_for_person(
        self,
        person_id: str,
        limit: int = 10,
        semantic_scope: str | None = None,
    ) -> PersonContextSource | None:
        """Return context source data for a person when present."""
        person_rows = self.runner.run(
            """
            MATCH (p:Person {id: $person_id})
            RETURN p.id AS person_id,
                   p.display_name AS display_name
            LIMIT 1
            """,
            {"person_id": person_id},
        )
        if not person_rows:
            return None

        scope = self._normalize_semantic_scope(semantic_scope)
        if scope is not None:
            items = self._scoped_items_for_person(person_id, scope, limit)
            return PersonContextSource(
                person_id=str(person_rows[0]["person_id"]),
                display_name=str(person_rows[0]["display_name"]) if person_rows[0].get("display_name") else None,
                items=items,
            )

        episode_rows = recent_episode_rows_for_person(self.runner, person_id, limit)
        event_rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[r]->(e:Event)
            WHERE type(r) = 'ATTENDED'
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            WITH e, place, properties(r) AS rel_props
            RETURN e.id AS item_id,
                   'event' AS item_type,
                   e.description AS text,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   rel_props.response AS role,
                   rel_props.source AS source
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"person_id": person_id, "limit": limit},
        )

        items = [self._row_to_context_item(row) for row in episode_rows + event_rows]
        items.sort(key=lambda item: item.start_time, reverse=True)
        return PersonContextSource(
            person_id=str(person_rows[0]["person_id"]),
            display_name=str(person_rows[0]["display_name"]) if person_rows[0].get("display_name") else None,
            items=items[:limit],
        )

    def _normalize_semantic_scope(self, semantic_scope: str | None) -> str | None:
        """Normalize an optional semantic scope string."""
        if semantic_scope is None:
            return None
        scope = semantic_scope.strip()
        return scope or None

    def _scoped_items_for_person(self, person_id: str, semantic_scope: str, limit: int) -> list[PersonContextItem]:
        """Return semantically scoped context items for a person."""
        if self.embeddings is None:
            raise ValueError("semantic_scope requires an embedding provider")

        embedding = self.embeddings.embed(semantic_scope)
        rows = []
        for index_name in ("episode_summary_embedding", "episode_transcript_embedding"):
            rows.extend(self._scoped_episode_rows(person_id, index_name, embedding, limit))

        best_rows: dict[str, dict[str, object]] = {}
        for row in rows:
            item_id = str(row["item_id"])
            existing = best_rows.get(item_id)
            if existing is None or self._row_score(row) > self._row_score(existing):
                best_rows[item_id] = row

        ordered_rows = sorted(
            best_rows.values(),
            key=lambda row: (self._row_score(row), str(row.get("start_time") or "")),
            reverse=True,
        )
        return [self._row_to_context_item(row) for row in ordered_rows[:limit]]

    def _scoped_episode_rows(
        self,
        person_id: str,
        index_name: str,
        embedding: list[float],
        limit: int,
    ) -> list[dict[str, object]]:
        """Fetch scoped episode rows from one vector index."""
        candidate_limit = max(limit * 5, 25)
        return self.runner.run(
            _vector_search_clause(index_name, "node", "candidate_limit")
            + """
            MATCH (:Person {id: $person_id})-[r:PARTICIPATED_IN]->(node)
            OPTIONAL MATCH (node)-[:OCCURRED_AT]->(place:Place)
            RETURN node.id AS item_id,
                   'episode' AS item_type,
                   ('Summary: ' + coalesce(node.summary, '') + '\nTranscript:\n' + coalesce(node.transcript, '')) AS text,
                   node.start_time AS start_time,
                   node.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.role AS role,
                   r.source AS source,
                   score AS score
            ORDER BY score DESC, node.start_time DESC
            LIMIT $limit
            """,
            {
                "candidate_limit": candidate_limit,
                "embedding": embedding,
                "person_id": person_id,
                "limit": limit,
            },
        )

    def _row_score(self, row: dict[str, object]) -> float:
        """Return a numeric score for a context row."""
        score = row.get("score")
        return score if isinstance(score, float) else 0.0

    def _row_to_context_item(self, row: dict[str, object]) -> PersonContextItem:
        """Convert a Neo4j row into a person context item."""
        text = str(row.get("text") or "")
        return PersonContextItem(
            item_id=str(row["item_id"]),
            item_type=str(row["item_type"]),
            text=text,
            start_time=str(row.get("start_time") or ""),
            end_time=str(row["end_time"]) if row.get("end_time") is not None else None,
            building_code=str(row["building_code"]) if row.get("building_code") is not None else None,
            room_id=str(row["room_id"]) if row.get("room_id") is not None else None,
            role=str(row["role"]) if row.get("role") is not None else None,
            source=str(row["source"]) if row.get("source") is not None else None,
            score=row.get("score") if isinstance(row.get("score"), float) else None,
            transcript_lines=self._parse_transcript_lines(text),
        )

    def _parse_transcript_lines(self, text: str) -> list[PersonContextTranscriptLine]:
        """Parse timestamped transcript lines from context text."""
        lines: list[PersonContextTranscriptLine] = []
        for raw_line in text.splitlines():
            match = _TRANSCRIPT_LINE_RE.match(raw_line.strip())
            if not match:
                continue
            lines.append(
                PersonContextTranscriptLine(
                    timestamp=match.group("timestamp"),
                    speaker=match.group("speaker").strip(),
                    text=match.group("text").strip(),
                )
            )
        return lines
