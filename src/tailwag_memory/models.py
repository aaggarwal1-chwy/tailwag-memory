from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PersonInput:
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
    building_code: str
    room_id: str


@dataclass(frozen=True)
class EventAttendeeInput:
    person: PersonInput
    response_time: str | None = None
    source: str = "caller"
    response: str = "accepted"


@dataclass(frozen=True)
class EpisodeInput:
    id: str
    episode_type: str
    start_time: str
    end_time: str | None
    summary: str
    transcript: str
    retention_class: str
    place: PlaceInput
    participants: list[PersonInput] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodeInput":
        place = payload.get("place") or {}
        participants = payload.get("participants") or []
        return cls(
            id=payload["id"],
            episode_type=payload["episode_type"],
            start_time=payload["start_time"],
            end_time=payload.get("end_time"),
            summary=payload["summary"],
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
        )


@dataclass(frozen=True)
class EventInput:
    id: str
    description: str
    start_time: str
    end_time: str | None
    place: PlaceInput
    accepted_attendees: list[EventAttendeeInput]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventInput":
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
    text: str
    person_id: str | None = None
    building_code: str | None = None
    room_id: str | None = None
    limit: int = 10
    target: str = "summary"


@dataclass(frozen=True)
class MemoryResult:
    episode_id: str
    summary: str
    transcript: str
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventResult:
    event_id: str
    description: str
    start_time: str
    end_time: str | None = None
    building_code: str | None = None
    room_id: str | None = None


@dataclass(frozen=True)
class PersonRecognitionResult:
    person_id: str
    display_name: str
    consent_status: str
    last_seen: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class PersonContextTranscriptLine:
    timestamp: str
    speaker: str
    text: str


@dataclass(frozen=True)
class PersonContextItem:
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
    person_id: str
    display_name: str | None
    items: list[PersonContextItem] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryItemInput:
    kind: str
    key: str
    summary: str
    source: str = "caller"
    source_ref: str = ""
    status: str = "active"
    observed_at: str = ""
    due_at: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_id: str | None = None


@dataclass(frozen=True)
class MemoryItemResult:
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
class PersonMemoryExtractionResult:
    person_id: str
    update_requested: bool = False
    created_memory_ids: list[str] = field(default_factory=list)
    updated_memory_ids: list[str] = field(default_factory=list)
    archived_memory_ids: list[str] = field(default_factory=list)
    skipped_ops: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class EpisodeMemoryExtractionResult:
    episode_id: str
    memory_results: list[PersonMemoryExtractionResult] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeRecordResult:
    episode_id: str
    memory_results: list[PersonMemoryExtractionResult] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)
