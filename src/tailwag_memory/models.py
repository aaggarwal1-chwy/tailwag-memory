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
    official_name: str | None = None
    email: str | None = None
    consent_status: str | None = None
    role: str = "participant"
    source: str = "caller"


@dataclass(frozen=True)
class RobotInput:
    """Caller-supplied robot identity and episode provenance."""

    id: str
    display_name: str
    role: str = "host"
    source: str = "argos"


@dataclass(frozen=True)
class RelayMessageInput:
    """Caller-supplied message content offered to the robot relay."""

    id: str
    sender_email: str
    recipient_email: str
    body: str
    deliver_after: str = ""
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelayPolicyResult:
    """Result of checking whether a message may enter the relay."""

    allowed: bool
    reason: str = ""
    sender_person_id: str = ""
    recipient_person_id: str = ""
    sender_email: str = ""
    recipient_email: str = ""
    sender_display_name: str = ""
    recipient_display_name: str = ""


@dataclass(frozen=True)
class RelayMessageEnvelope:
    """Claimed relay metadata that intentionally excludes message content."""

    message_id: str
    sender_person_id: str = ""
    recipient_person_id: str = ""
    sender_email: str = ""
    recipient_email: str = ""
    sender_display_name: str = ""
    recipient_display_name: str = ""
    assigned_robot_id: str = ""
    created_at: str = ""
    deliver_after: str = ""
    expires_at: str = ""
    status: str = ""
    claim_token: str = ""


@dataclass(frozen=True)
class RelayDeliveryAttempt:
    """Machine-controlled playback attempt for one claimed relay message."""

    message_id: str
    claim_token: str
    status: str
    started_at: str = ""
    completed_at: str = ""
    failed_at: str = ""
    failure_reason: str = ""
    audio_started: bool = False


@dataclass(frozen=True)
class RelayMessageStatus:
    """Sender-visible relay status that intentionally excludes message content."""

    message_id: str
    sender_person_id: str = ""
    recipient_person_id: str = ""
    sender_email: str = ""
    recipient_email: str = ""
    sender_display_name: str = ""
    recipient_display_name: str = ""
    assigned_robot_id: str = ""
    status: str = ""
    created_at: str = ""
    deliver_after: str = ""
    expires_at: str = ""
    updated_at: str = ""
    last_failure_reason: str = ""
    last_failure_at: str = ""


@dataclass(frozen=True)
class RelayTransitionResult:
    """Result of a claim-bound relay transition."""

    message_id: str
    status: str
    claim_token: str = ""
    body: str | None = None
    reason: str = ""


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
    robots: list[RobotInput] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodeInput":
        """Build an episode input from a dictionary payload."""

        place = payload.get("place") or {}
        participants = payload.get("participants") or []
        mentioned_people = payload.get("mentioned_people") or []
        robots = payload.get("robots") or []
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
                    official_name=item.get("official_name"),
                    email=item.get("email"),
                    consent_status=item.get("consent_status"),
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
                        official_name=item["person"].get("official_name"),
                        email=item["person"].get("email"),
                        consent_status=item["person"].get("consent_status"),
                        role=item["person"].get("role", "mentioned"),
                        source=item["person"].get("source", item.get("source", "caller")),
                    ),
                    source=item.get("source", "caller"),
                )
                for item in mentioned_people
            ],
            robots=[
                RobotInput(
                    id=item["id"],
                    display_name=item["display_name"],
                    role=item.get("role", "host"),
                    source=item.get("source", "argos"),
                )
                for item in robots
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
                        official_name=item["person"].get("official_name"),
                        email=item["person"].get("email"),
                        consent_status=item["person"].get("consent_status"),
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
    robot_id: str | None = None


@dataclass(frozen=True)
class RobotParticipationResult:
    """Robot identity and provenance attached to an episode result."""

    robot_id: str
    display_name: str
    role: str
    source: str


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
    robots: list[RobotParticipationResult] = field(default_factory=list)


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
class DirectoryPersonRecord:
    """Normalized employee-directory row owned by Tailwag."""

    official_name: str
    username: str
    site_code: str = ""
    employee_email: str = ""
    business_title: str = ""
    job_family: str = ""
    job_family_group: str = ""
    job_level: str = ""
    c_level: str = ""
    manager_name: str = ""
    cost_center: str = ""
    senior_leadership_team: str = ""
    business_function: str = ""
    tenure: str = ""


@dataclass(frozen=True)
class DirectorySyncResult:
    """Result of loading directory people into Tailwag."""

    site_code: str
    records_seen: int
    records_written: int


@dataclass(frozen=True)
class IdentityCandidate:
    """One possible directory identity match."""

    official_name: str
    username: str
    employee_email: str = ""
    business_title: str = ""
    tenure: str = ""
    manager_name: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class IdentityResolutionResult:
    """Employee-directory identity resolution result."""

    success: bool
    status: str
    message: str
    data: dict[str, Any] | None = None
    candidates: list[IdentityCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class VerifiedProfile:
    """Verified employee profile returned for enrollment rehydration."""

    person_id: str
    official_name: str
    username: str
    employee_email: str = ""
    business_title: str = ""
    tenure: str = ""
    manager_name: str = ""
    directory_profile_lines: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonProfile:
    """Prompt/runtime person profile projection."""

    person_id: str
    display_name: str
    email: str = ""
    consent_status: str = ""
    status: str = "active"
    interaction_count: int = 0
    last_seen: str | None = None
    directory_profile_lines: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BiometricCandidate:
    """One biometric reference search candidate."""

    person_id: str
    display_name: str = ""
    score: float = 0.0
    consent_status: str = ""
    reference_id: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BiometricSearchResult:
    """Thresholded biometric search response."""

    modality: str
    candidates: list[BiometricCandidate] = field(default_factory=list)
    recognized: bool = False
    status: str = "rejected"
    reason: str = "no_match"
    threshold: float = 0.0
    margin_threshold: float = 0.0
    top_score: float = 0.0
    runner_up_score: float = 0.0
    margin: float = 0.0


@dataclass(frozen=True)
class BiometricEnrollmentResult:
    """Result of storing a biometric reference."""

    saved: bool
    status: str
    reason: str
    person_id: str
    reference_id: str = ""


@dataclass(frozen=True)
class BiometricUpdateResult:
    """Result of adaptively updating a biometric reference aggregate."""

    accepted: bool
    status: str
    reason: str
    person_id: str
    reference_id: str = ""
    modality: str = ""
    sample_count: int = 0
    target_sample_count: int = 0
    similarity: float = 0.0


@dataclass(frozen=True)
class OwnerResolutionResult:
    """Final turn-owner resolution result."""

    audio_speaker_id: str | None
    top_score: float
    runner_up_score: float
    margin: float
    speaker_visible: bool
    owner_id: str | None
    owner_source: str
    owner_confidence: float
    unresolved_reason: str = ""


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
    memory_extraction_job_id: str | None = None
