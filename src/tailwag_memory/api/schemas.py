from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


def _model_dump(model: BaseModel) -> dict[str, Any]:
    """Return a Pydantic model as a plain dictionary across supported versions."""
    dump = getattr(model, "model_dump", None)
    return dump() if callable(dump) else model.dict()


class PersonContextRequest(BaseModel):
    """Request body for prompt-ready person context."""

    person_id: str
    limit: int = 10
    semantic_scope: str | None = None
    current_text: str | None = None
    now: datetime | None = None
    memory_limit: int = 12
    recent_episode_limit: int = 5


class PersonContextResponse(BaseModel):
    """Prompt-ready markdown context response."""

    person_id: str
    context_markdown: str
    generated_at: str | None = None


class EpisodeRecordRequest(BaseModel):
    """Request body for recording one episode."""

    episode: "EpisodePayload"
    extract_memory: bool = True


class SemanticSearchRequest(BaseModel):
    """Request body for per-person semantic memory search."""

    text: str
    person_id: str
    building_code: str | None = None
    limit: int = 5
    now: datetime | None = None


class PersonPayload(BaseModel):
    """HTTP shape for PersonInput."""

    id: str
    display_name: str | None = None
    official_name: str | None = None
    email: str | None = None
    consent_status: str | None = None
    role: str = "participant"
    source: str = "caller"

    def as_kwargs(self) -> dict[str, Any]:
        """Return a version-compatible Pydantic dict."""
        return _model_dump(self)


class PlacePayload(BaseModel):
    """HTTP shape for PlaceInput."""

    building_code: str
    room_id: str


class EpisodeMentionPayload(BaseModel):
    """HTTP shape for EpisodeMentionInput."""

    person: PersonPayload
    source: str = "caller"


class EpisodePayload(BaseModel):
    """HTTP shape for EpisodeInput."""

    id: str
    episode_type: str
    start_time: str
    end_time: str | None = None
    transcript: str
    retention_class: str
    place: PlacePayload
    participants: list[PersonPayload] = Field(default_factory=list)
    mentioned_people: list[EpisodeMentionPayload] = Field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return an EpisodeInput-compatible dictionary."""
        return _model_dump(self)


class PersonUpsertRequest(BaseModel):
    """Request body for creating or updating a person."""

    person: PersonPayload


class PersonArchiveRequest(BaseModel):
    """Request body for archiving a person."""

    person_id: str


class PersonRekeyByEmailRequest(BaseModel):
    """Request body for email-based person rekeying."""

    email: str = Field(..., min_length=1)
    new_person_id: str = Field(..., min_length=1)
