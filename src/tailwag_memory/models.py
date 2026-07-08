from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PersonInput:
    """Caller-supplied person data for ingestion."""

    id: str
    display_name: str | None = None
    email: str | None = None
    consent_status: str | None = None
    face_embedding: list[float] | None = None
    audio_embedding: list[float] | None = None
    role: str = "participant"
    source: str = "caller"


@dataclass(frozen=True)
class PlaceInput:
    """Building and room identifier for a place."""

    building_code: str
    room_id: str


@dataclass(frozen=True)
class EventAttendeeInput:
    """Accepted event attendee data for ingestion."""

    person: PersonInput
    response_time: str | None = None
    source: str = "caller"
    response: str = "accepted"


@dataclass(frozen=True)
class EpisodeMentionInput:
    """Person mentioned in an episode without implying participation."""

    person: PersonInput
    source: str = "caller"


@dataclass(frozen=True)
class EpisodeInput:
    """Caller-supplied episode payload for ingestion."""

    id: str
    episode_type: str
    start_time: str
    end_time: str | None
    transcript: str
    retention_class: str
    place: PlaceInput
    participants: list[PersonInput] = field(default_factory=list)
    mentioned_people: list[EpisodeMentionInput] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodeInput":
        """Build an episode input from a dictionary payload."""

        place = payload.get("place") or {}
        participants = payload.get("participants") or []
        mentioned_people = payload.get("mentioned_people") or []
        return cls(
            id=payload["id"],
            episode_type=payload["episode_type"],
            start_time=payload["start_time"],
            end_time=payload.get("end_time"),
            transcript=payload["transcript"],
            retention_class=payload["retention_class"],
            place=PlaceInput(
                building_code=place["building_code"],
                room_id=place["room_id"],
            ),
            participants=[
                PersonInput(
                    id=item["id"],
                    display_name=item.get("display_name"),
                    email=item.get("email"),
                    consent_status=item.get("consent_status"),
                    face_embedding=item.get("face_embedding"),
                    audio_embedding=item.get("audio_embedding"),
                    role=item.get("role", "participant"),
                    source=item.get("source", "caller"),
                )
                for item in participants
            ],
            mentioned_people=[
                EpisodeMentionInput(
                    person=PersonInput(
                        id=item["person"]["id"],
                        display_name=item["person"].get("display_name"),
                        email=item["person"].get("email"),
                        consent_status=item["person"].get("consent_status"),
                        face_embedding=item["person"].get("face_embedding"),
                        audio_embedding=item["person"].get("audio_embedding"),
                        role=item["person"].get("role", "mentioned"),
                        source=item["person"].get("source", item.get("source", "caller")),
                    ),
                    source=item.get("source", "caller"),
                )
                for item in mentioned_people
            ],
        )


@dataclass(frozen=True)
class EventInput:
    """Caller-supplied event payload for ingestion."""

    id: str
    description: str
    start_time: str
    end_time: str | None
    place: PlaceInput
    accepted_attendees: list[EventAttendeeInput]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventInput":
        """Build an event input from a dictionary payload."""

        place = payload.get("place") or {}
        accepted_attendees = payload["accepted_attendees"]
        return cls(
            id=payload["id"],
            description=payload["description"],
            start_time=payload["start_time"],
            end_time=payload.get("end_time"),
            place=PlaceInput(
                building_code=place["building_code"],
                room_id=place["room_id"],
            ),
            accepted_attendees=[
                EventAttendeeInput(
                    person=PersonInput(
                        id=item["person"]["id"],
                        display_name=item["person"].get("display_name"),
                        email=item["person"].get("email"),
                        consent_status=item["person"].get("consent_status"),
                        face_embedding=item["person"].get("face_embedding"),
                        audio_embedding=item["person"].get("audio_embedding"),
                        role=item["person"].get("role", "attendee"),
                        source=item["person"].get("source", item.get("source", "caller")),
                    ),
                    response_time=item.get("response_time"),
                    source=item.get("source", "caller"),
                    response=item.get("response", "accepted"),
                )
                for item in accepted_attendees
            ],
        )


@dataclass(frozen=True)
class SearchQuery:
    """Retrieval query parameters for memory searches."""

    text: str
    person_id: str | None = None
    building_code: str | None = None
    room_id: str | None = None
    limit: int = 10


@dataclass(frozen=True)
class EpisodeMemoryResult:
    """Episode search result with optional time, place, and vector score."""

    episode_id: str
    transcript: str
    score: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    building_code: str | None = None
    room_id: str | None = None


@dataclass(frozen=True)
class EventResult:
    """Event lookup result with place and time fields."""

    event_id: str
    description: str
    start_time: str
    end_time: str | None = None
    building_code: str | None = None
    room_id: str | None = None


@dataclass(frozen=True)
class PersonRecognitionResult:
    """Person recognition match with consent and score data."""

    person_id: str
    display_name: str
    consent_status: str
    last_seen: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class PersonContextTranscriptLine:
    """Transcript line included in person context output."""

    timestamp: str
    speaker: str
    text: str


@dataclass(frozen=True)
class PersonContextItem:
    """Context item associated with a person."""

    item_id: str
    item_type: str
    text: str
    start_time: str
    end_time: str | None = None
    building_code: str | None = None
    room_id: str | None = None
    role: str | None = None
    source: str | None = None
    score: float | None = None
    transcript_lines: list[PersonContextTranscriptLine] = field(default_factory=list)


@dataclass(frozen=True)
class PersonContextSource:
    """Grouped context items for a person."""

    person_id: str
    display_name: str | None
    items: list[PersonContextItem] = field(default_factory=list)


@dataclass(frozen=True)
class PersonTimelineTranscriptSnippet:
    """Transcript snippet included in a person timeline item."""

    timestamp: str
    speaker: str
    text: str


@dataclass(frozen=True)
class PersonTimelineItem:
    """Read-only person timeline item for inspect reports."""

    person_id: str
    display_name: str | None
    item_id: str
    item_type: str
    start_time: str
    end_time: str | None = None
    episode_id: str | None = None
    event_id: str | None = None
    text: str = ""
    building_code: str | None = None
    room_id: str | None = None
    role: str | None = None
    source: str | None = None
    has_memory_items: bool = False
    memory_item_count: int = 0
    memory_item_ids: list[str] = field(default_factory=list)
    transcript_snippets: list[PersonTimelineTranscriptSnippet] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryItemInput:
    """Caller-supplied memory item creation payload."""

    kind: str
    key: str
    summary: str
    source: str = "caller"
    source_ref: str = ""
    observed_at: str = ""
    due_at: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryItemResult:
    """Persisted memory item result with metadata and score."""

    memory_id: str
    person_id: str
    kind: str
    key: str
    summary: str
    source: str
    source_ref: str = ""
    status: str = "active"
    observed_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    due_at: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


@dataclass(frozen=True)
class MemoryItemMergeResult:
    """Result for merging related memory items into one active memory."""

    person_id: str
    merged_memory_id: str
    superseded_memory_ids: list[str] = field(default_factory=list)
    linked_episode_count: int = 0
    skipped_source_memory_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonMemoryExtractionResult:
    """Per-person result for episode memory extraction."""

    person_id: str
    update_requested: bool = False
    created_memory_ids: list[str] = field(default_factory=list)
    addressed_memory_ids: list[str] = field(default_factory=list)
    supported_memory_ids: list[str] = field(default_factory=list)
    skipped_ops: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class EpisodeMemoryExtractionResult:
    """Aggregate memory extraction result for one episode."""

    episode_id: str
    memory_results: list[PersonMemoryExtractionResult] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PersonMemoryConsolidationResult:
    """Per-person result for semantic memory consolidation."""

    person_id: str
    update_requested: bool = False
    created_memory_ids: list[str] = field(default_factory=list)
    skipped_ops: list[dict[str, Any]] = field(default_factory=list)
    candidate_episode_ids: list[str] = field(default_factory=list)
    provider_called: bool = False
    error: str | None = None
    superseded_memory_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryConsolidationResult:
    """Aggregate result for semantic memory consolidation."""

    person_results: list[PersonMemoryConsolidationResult] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeRecordResult:
    """Episode recording result with memory extraction details."""

    episode_id: str
    memory_results: list[PersonMemoryExtractionResult] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)
