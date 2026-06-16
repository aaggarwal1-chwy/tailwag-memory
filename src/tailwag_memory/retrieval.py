from __future__ import annotations

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .models import EventResult, MemoryResult, PersonRecognitionResult, SearchQuery


class EpisodeRetrievalService:
    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        self.runner = runner
        self.embeddings = embeddings

    def by_person(self, person_id: str, limit: int = 10) -> list[MemoryResult]:
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:PARTICIPATED_IN]->(e:Episode)
            RETURN e.id AS episode_id,
                   e.summary AS summary,
                   e.transcript AS transcript
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"person_id": person_id, "limit": limit},
        )
        return [self._row_to_result(row) for row in rows]

    def by_place(self, building_code: str, room_id: str, limit: int = 10) -> list[MemoryResult]:
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

    def vector_search(self, text: str, target: str = "summary", limit: int = 10) -> list[MemoryResult]:
        index_name = self._index_name(target)
        rows = self.runner.run(
            """
            CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
            YIELD node, score
            RETURN node.id AS episode_id,
                   node.summary AS summary,
                   node.transcript AS transcript,
                   score AS score
            ORDER BY score DESC
            """,
            {
                "index_name": index_name,
                "limit": limit,
                "embedding": self.embeddings.embed(text),
            },
        )
        return [self._row_to_result(row) for row in rows]

    def hybrid_search(self, query: SearchQuery) -> list[MemoryResult]:
        index_name = self._index_name(query.target)
        rows = self.runner.run(
            """
            CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
            YIELD node, score
            OPTIONAL MATCH (person:Person)-[:PARTICIPATED_IN]->(node)
            OPTIONAL MATCH (node)-[:OCCURRED_AT]->(place:Place)
            WITH node, score, collect(DISTINCT person.id) AS person_ids, collect(DISTINCT place) AS places
            WHERE ($person_id IS NULL OR $person_id IN person_ids)
              AND (
                $building_code IS NULL
                OR any(place IN places WHERE place.building_code = $building_code AND place.room_id = $room_id)
              )
            RETURN node.id AS episode_id,
                   node.summary AS summary,
                   node.transcript AS transcript,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {
                "index_name": index_name,
                "limit": query.limit,
                "embedding": self.embeddings.embed(query.text),
                "person_id": query.person_id,
                "building_code": query.building_code,
                "room_id": query.room_id,
            },
        )
        return [self._row_to_result(row) for row in rows]

    def _index_name(self, target: str) -> str:
        if target == "summary":
            return "episode_summary_embedding"
        if target == "transcript":
            return "episode_transcript_embedding"
        raise ValueError("target must be 'summary' or 'transcript'")

    def _row_to_result(self, row: dict[str, object]) -> MemoryResult:
        return MemoryResult(
            episode_id=str(row["episode_id"]),
            summary=str(row.get("summary") or ""),
            transcript=str(row.get("transcript") or ""),
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )


class PersonRecognitionService:
    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def by_face_embedding(self, embedding: list[float], limit: int = 10) -> list[PersonRecognitionResult]:
        return self._vector_search("person_face_embedding", embedding, limit)

    def by_audio_embedding(self, embedding: list[float], limit: int = 10) -> list[PersonRecognitionResult]:
        return self._vector_search("person_audio_embedding", embedding, limit)

    def _vector_search(
        self,
        index_name: str,
        embedding: list[float],
        limit: int,
    ) -> list[PersonRecognitionResult]:
        rows = self.runner.run(
            """
            CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
            YIELD node, score
            RETURN node.id AS person_id,
                   node.display_name AS display_name,
                   node.consent_status AS consent_status,
                   node.last_seen AS last_seen,
                   score AS score
            ORDER BY score DESC
            """,
            {
                "index_name": index_name,
                "limit": limit,
                "embedding": embedding,
            },
        )
        return [self._row_to_result(row) for row in rows]

    def _row_to_result(self, row: dict[str, object]) -> PersonRecognitionResult:
        return PersonRecognitionResult(
            person_id=str(row["person_id"]),
            display_name=str(row.get("display_name") or ""),
            consent_status=str(row.get("consent_status") or ""),
            last_seen=str(row["last_seen"]) if row.get("last_seen") is not None else None,
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )


class EventRetrievalService:
    def __init__(self, runner: QueryRunner) -> None:
        self.runner = runner

    def by_place(self, building_code: str, room_id: str, limit: int = 10) -> list[EventResult]:
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
        return EventResult(
            event_id=str(row["event_id"]),
            description=str(row.get("description") or ""),
            start_time=str(row.get("start_time") or ""),
            end_time=str(row["end_time"]) if row.get("end_time") is not None else None,
            building_code=str(row.get("building_code") or ""),
            room_id=str(row.get("room_id") or ""),
        )
