from __future__ import annotations

import re

from ..db import QueryRunner
from ..models import PersonTimelineItem, PersonTimelineTranscriptSnippet
from ..person_episode_rows import person_episode_rows
from ..transcript_parsing import row_speaker_labels, target_transcript_turns

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class PersonTimelineRetrievalService:
    """Read person timeline items for inspect reports."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store dependencies for timeline retrieval."""
        self.runner = runner

    def items(self, *, person_id: str | None = None, limit: int = 100) -> list[PersonTimelineItem]:
        """Return recent episode and event timeline items for one or more people."""
        bounded_limit = _bounded_limit(limit)
        if bounded_limit == 0:
            return []

        normalized_person_id = _normalize_optional_text(person_id)
        parameters = {"person_id": normalized_person_id, "limit": bounded_limit}
        rows = self._episode_rows(parameters) + self._event_rows(parameters)
        items = [self._row_to_timeline_item(row) for row in rows]
        items.sort(key=lambda item: (item.start_time or "", item.person_id, item.item_id), reverse=True)
        return items[:bounded_limit]

    def _episode_rows(self, parameters: dict[str, object]) -> list[dict[str, object]]:
        """Fetch episode participation rows for the timeline."""
        return person_episode_rows(
            self.runner,
            person_id=str(parameters.get("person_id") or "") or None,
            limit=int(parameters["limit"]),
            include_context_fields=True,
            include_event_placeholder=True,
            include_memory_count=True,
            always_include_person_filter=True,
        )

    def _event_rows(self, parameters: dict[str, object]) -> list[dict[str, object]]:
        """Fetch attended event rows for the timeline."""
        return self.runner.run(
            """
            MATCH (person:Person)-[r]->(e:Event)
            WHERE type(r) = 'ATTENDED'
              AND ($person_id IS NULL OR person.id = $person_id)
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            RETURN person.id AS person_id,
                   person.display_name AS display_name,
                   e.id AS item_id,
                   'event' AS item_type,
                   null AS episode_id,
                   e.id AS event_id,
                   coalesce(e.description, '') AS text,
                   null AS transcript,
                   [] AS speaker_labels,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   place.building_code AS building_code,
                   place.room_id AS room_id,
                   r.response AS role,
                   r.source AS source,
                   0 AS memory_item_count,
                   [] AS memory_item_ids
            ORDER BY e.start_time DESC, person.id ASC
            LIMIT $limit
            """,
            parameters,
        )

    def _row_to_timeline_item(self, row: dict[str, object]) -> PersonTimelineItem:
        """Convert a Neo4j row into a person timeline item."""
        item_type = str(row.get("item_type") or "")
        item_id = str(row.get("item_id") or "")
        transcript = str(row.get("transcript") or "")
        snippets = self._transcript_snippets(row, transcript) if item_type == "episode" else []
        text = " ".join(snippet.text for snippet in snippets) if snippets else _timeline_text(row.get("text"))
        return PersonTimelineItem(
            person_id=str(row.get("person_id") or ""),
            display_name=str(row["display_name"]) if row.get("display_name") else None,
            item_id=item_id,
            item_type=item_type,
            episode_id=str(row["episode_id"]) if row.get("episode_id") is not None else None,
            event_id=str(row["event_id"]) if row.get("event_id") is not None else None,
            text=text,
            start_time=str(row.get("start_time") or ""),
            end_time=str(row["end_time"]) if row.get("end_time") is not None else None,
            building_code=str(row["building_code"]) if row.get("building_code") is not None else None,
            room_id=str(row["room_id"]) if row.get("room_id") is not None else None,
            role=str(row["role"]) if row.get("role") is not None else None,
            source=str(row["source"]) if row.get("source") is not None else None,
            has_memory_items=_row_memory_item_count(row) > 0,
            memory_item_count=_row_memory_item_count(row),
            memory_item_ids=_row_memory_item_ids(row),
            transcript_snippets=snippets,
        )

    def _transcript_snippets(
        self,
        row: dict[str, object],
        transcript: str,
    ) -> list[PersonTimelineTranscriptSnippet]:
        """Return target-person transcript snippets for an episode row."""
        person_id = str(row.get("person_id") or "")
        display_name = str(row.get("display_name") or "")
        turns = target_transcript_turns(
            transcript,
            person_id=person_id,
            display_name=display_name,
            speaker_labels=row_speaker_labels(row),
        )
        return [
            PersonTimelineTranscriptSnippet(
                timestamp=turn.timestamp,
                speaker=turn.speaker,
                text=turn.text,
            )
            for turn in turns[:5]
        ]


def _bounded_limit(limit: int) -> int:
    """Return a non-negative rendering/retrieval limit."""
    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return 10


def _normalize_optional_text(value: str | None) -> str | None:
    """Normalize optional user text."""
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _timeline_text(value: object) -> str:
    """Return a compact timeline text field."""
    rendered = _CONTROL_CHARS_RE.sub(" ", str(value or ""))
    rendered = " ".join(rendered.split())
    if len(rendered) <= 360:
        return rendered
    return rendered[:357].rstrip() + "..."


def _row_memory_item_count(row: dict[str, object]) -> int:
    """Return the memory item count for a timeline row."""
    try:
        return max(0, int(row.get("memory_item_count") or 0))
    except (TypeError, ValueError):
        return 0


def _row_memory_item_ids(row: dict[str, object]) -> list[str]:
    """Return linked memory item IDs for a timeline row."""
    raw = row.get("memory_item_ids")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    rendered: list[str] = []
    for value in raw:
        item_id = str(value or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            rendered.append(item_id)
    return rendered
