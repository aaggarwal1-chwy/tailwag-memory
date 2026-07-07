from __future__ import annotations

from ..db import QueryRunner
from ..transcript_parsing import target_transcript_turns
from .models import InspectTranscriptLine, PersonEpisodeTranscriptPoint


def recent_person_episode_rows(runner: QueryRunner, limit: int) -> list[dict[str, object]]:
    """Fetch recent episode rows for person/episode participation pairs."""
    return runner.run(
        """
            MATCH (person:Person)-[r:PARTICIPATED_IN]->(e:Episode)
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            OPTIONAL MATCH (speaker:Person)-[:PARTICIPATED_IN]->(e)
            OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)
            WITH e, r, person, place,
                 collect(DISTINCT speaker.id) + collect(DISTINCT speaker.display_name) AS speaker_labels,
                 count(DISTINCT memory) AS memory_item_count
            RETURN e.id AS episode_id,
                   person.id AS person_id,
                   person.display_name AS display_name,
                   speaker_labels AS speaker_labels,
                   e.transcript AS transcript,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.role AS role,
                   r.source AS source,
                   memory_item_count AS memory_item_count
            ORDER BY e.start_time DESC, person.id ASC
            LIMIT $limit
            """,
        {"limit": limit},
    )


class PersonEpisodeTranscriptService:
    """Extract person-specific episode transcript text for inspection utilities."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store the Neo4j query runner."""
        self.runner = runner

    def points(
        self,
        *,
        person_id: str | None = None,
        limit: int = 100,
    ) -> list[PersonEpisodeTranscriptPoint]:
        """Return recent person/episode transcript points."""
        bounded_limit = _bounded_positive_limit(limit, default=100)
        if bounded_limit == 0:
            return []
        rendered_person_id = str(person_id or "").strip()
        if rendered_person_id:
            rows = _recent_episode_rows_for_person(self.runner, rendered_person_id, bounded_limit)
        else:
            rows = recent_person_episode_rows(self.runner, bounded_limit)

        points: list[PersonEpisodeTranscriptPoint] = []
        for row in rows:
            point = self._row_to_point(row)
            if point is not None:
                points.append(point)
        return points

    def _row_to_point(self, row: dict[str, object]) -> PersonEpisodeTranscriptPoint | None:
        """Convert a Neo4j row into a person transcript point when text is available."""
        transcript = str(row.get("transcript") or row.get("text") or "")
        person_id = str(row.get("person_id") or "").strip()
        display_name = str(row.get("display_name") or "").strip() or None
        turns = target_transcript_turns(
            transcript,
            person_id=person_id,
            display_name=display_name or "",
            speaker_labels=_row_speaker_labels(row),
        )
        if not turns:
            return None
        lines = [
            InspectTranscriptLine(
                timestamp=turn.timestamp,
                speaker=turn.speaker,
                text=turn.text,
            )
            for turn in turns
        ]

        memory_item_count = _row_memory_item_count(row)
        return PersonEpisodeTranscriptPoint(
            person_id=person_id,
            display_name=display_name,
            episode_id=str(row.get("episode_id") or row.get("item_id") or ""),
            text=" ".join(line.text for line in lines),
            line_count=len(lines),
            start_time=str(row["start_time"]) if row.get("start_time") is not None else None,
            end_time=str(row["end_time"]) if row.get("end_time") is not None else None,
            building_code=str(row["building_code"]) if row.get("building_code") is not None else None,
            room_id=str(row["room_id"]) if row.get("room_id") is not None else None,
            role=str(row["role"]) if row.get("role") is not None else None,
            source=str(row["source"]) if row.get("source") is not None else None,
            has_memory_items=memory_item_count > 0,
            memory_item_count=memory_item_count,
            transcript_lines=lines,
        )


def _recent_episode_rows_for_person(runner: QueryRunner, person_id: str, limit: int) -> list[dict[str, object]]:
    """Fetch recent episode rows linked to a person for inspection."""
    return runner.run(
        """
            MATCH (person:Person {id: $person_id})-[r:PARTICIPATED_IN]->(e:Episode)
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            OPTIONAL MATCH (speaker:Person)-[:PARTICIPATED_IN]->(e)
            OPTIONAL MATCH (person)-[:HAS_MEMORY]->(memory:MemoryItem)-[:SUPPORTED_BY]->(e)
            WITH e, r, person, place,
                 collect(DISTINCT speaker.id) + collect(DISTINCT speaker.display_name) AS speaker_labels,
                 count(DISTINCT memory) AS memory_item_count
            RETURN e.id AS episode_id,
                   person.id AS person_id,
                   person.display_name AS display_name,
                   speaker_labels AS speaker_labels,
                   e.transcript AS transcript,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.role AS role,
                   r.source AS source,
                   memory_item_count AS memory_item_count
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
        {"person_id": person_id, "limit": limit},
    )


def _bounded_positive_limit(limit: int, *, default: int) -> int:
    """Return a non-negative limit with a caller-provided default."""
    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return default


def _row_speaker_labels(row: dict[str, object]) -> list[str]:
    """Return known speaker labels from a Neo4j retrieval row."""
    raw_labels = row.get("speaker_labels")
    if not isinstance(raw_labels, list):
        return []
    return [str(label) for label in raw_labels if str(label or "").strip()]


def _row_memory_item_count(row: dict[str, object]) -> int:
    """Return the memory item count for an inspection row."""
    try:
        return max(0, int(row.get("memory_item_count") or 0))
    except (TypeError, ValueError):
        return 0
