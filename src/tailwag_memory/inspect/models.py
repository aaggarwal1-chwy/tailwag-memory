from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InspectTranscriptLine:
    """Transcript line included in an inspection point."""

    timestamp: str
    speaker: str
    text: str


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
    transcript_lines: list[InspectTranscriptLine] = field(default_factory=list)


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
