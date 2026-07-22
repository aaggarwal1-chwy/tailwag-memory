from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InspectReport:
    """Common report envelope for Tailwag inspect utilities."""

    title: str
    generated_at: str
    filters: dict[str, object] = field(default_factory=dict)
    records: list[dict[str, object]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InspectSankeyLink:
    """One weighted flow link in a read-only Sankey inspection report."""

    source: str
    target: str
    count: int


@dataclass(frozen=True)
class InspectFollowupValidityItem:
    """Follow-up memory item grouped by validity-window duration."""

    memory_id: str
    person_id: str
    display_name: str | None
    summary: str
    status: str
    followup_state: str
    due_at: str = ""
    expires_at: str = ""
    validity_seconds: int | None = None
    validity_bucket: str = "invalid"


@dataclass(frozen=True)
class InspectTranscriptLine:
    """Transcript line included in an inspection point."""

    timestamp: str
    speaker: str
    text: str


@dataclass(frozen=True)
class InspectRelatedMemoryItem:
    """Memory item summary linked to an inspection transcript point."""

    memory_id: str
    kind: str
    status: str
    summary: str


@dataclass(frozen=True)
class PersonEpisodeTranscriptPoint:
    """Person-specific transcript text extracted from one episode."""

    person_id: str
    display_name: str | None
    episode_id: str
    text: str
    line_count: int
    start_time: str | None = None
    end_time: str | None = None
    building_code: str | None = None
    room_id: str | None = None
    role: str | None = None
    source: str | None = None
    has_memory_items: bool = False
    memory_item_count: int = 0
    transcript_lines: list[InspectTranscriptLine] = field(default_factory=list)
    related_memory_items: list[InspectRelatedMemoryItem] = field(default_factory=list)


@dataclass(frozen=True)
class AffectScore:
    """Valence/arousal score with provider metadata."""

    valence: float
    arousal: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonEpisodeAffectPoint:
    """Affect score for one person's episode transcript text."""

    transcript: PersonEpisodeTranscriptPoint
    valence: float
    arousal: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InspectMemoryAddressedEpisode:
    """Episode evidence that addressed a follow-up memory item."""

    episode_id: str
    addressed_at: str = ""


@dataclass(frozen=True)
class InspectMemoryItem:
    """Memory item row shaped for read-only inspection reports."""

    memory_id: str
    person_id: str
    display_name: str | None
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
    supported_episode_ids: list[str] = field(default_factory=list)
    addressed_by: list[InspectMemoryAddressedEpisode] = field(default_factory=list)
    superseded_by_memory_ids: list[str] = field(default_factory=list)
    supersedes_memory_ids: list[str] = field(default_factory=list)
    followup_state: str = "not_followup"
