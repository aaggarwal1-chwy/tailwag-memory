from __future__ import annotations

from ..db import QueryRunner
from ..person_episode_rows import person_episode_rows
from ..transcript_parsing import row_speaker_labels, target_transcript_turns
from .models import InspectRelatedMemoryItem, InspectTranscriptLine, PersonEpisodeTranscriptPoint


def recent_person_episode_rows(runner: QueryRunner, limit: int) -> list[dict[str, object]]:
    """Fetch recent episode rows for person/episode participation pairs."""
    return person_episode_rows(runner, limit=limit, include_memory_count=True, include_memory_items=True)


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
            speaker_labels=row_speaker_labels(row),
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
        related_memory_items = _row_related_memory_items(row)
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
            related_memory_items=related_memory_items,
        )


def _recent_episode_rows_for_person(runner: QueryRunner, person_id: str, limit: int) -> list[dict[str, object]]:
    """Fetch recent episode rows linked to a person for inspection."""
    return person_episode_rows(
        runner,
        person_id=person_id,
        limit=limit,
        include_memory_count=True,
        include_memory_items=True,
    )


def _bounded_positive_limit(limit: int, *, default: int) -> int:
    """Return a non-negative limit with a caller-provided default."""
    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return default


def _row_memory_item_count(row: dict[str, object]) -> int:
    """Return the memory item count for an inspection row."""
    try:
        return max(0, int(row.get("memory_item_count") or 0))
    except (TypeError, ValueError):
        return 0


def _row_related_memory_items(row: dict[str, object]) -> list[InspectRelatedMemoryItem]:
    """Return related memory item summaries for an inspection row."""
    items: list[InspectRelatedMemoryItem] = []
    seen: set[str] = set()
    for raw in _row_list(row.get("related_memory_items")):
        if not isinstance(raw, dict):
            continue
        memory_id = str(raw.get("memory_id") or "").strip()
        if not memory_id or memory_id in seen:
            continue
        seen.add(memory_id)
        items.append(
            InspectRelatedMemoryItem(
                memory_id=memory_id,
                kind=str(raw.get("kind") or "").strip(),
                status=str(raw.get("status") or "").strip(),
                summary=str(raw.get("summary") or "").strip(),
            )
        )
    return items


def _row_list(value: object) -> list[object]:
    """Return a Neo4j list-ish value as a plain list."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []
