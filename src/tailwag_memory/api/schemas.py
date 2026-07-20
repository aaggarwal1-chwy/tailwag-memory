from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict, field_validator
except ImportError:  # pragma: no cover - Pydantic v1 compatibility
    ConfigDict = None
    from pydantic import validator as _validator

    def field_validator(*fields: str):
        return _validator(*fields, allow_reuse=True)


RAW_MEDIA_KEYS = {
    "audio",
    "audio_pcm16",
    "audio_url",
    "audiourl",
    "base64",
    "bytes",
    "clip",
    "confidence",
    "crop",
    "data_url",
    "dataurl",
    "face_embedding",
    "face_image",
    "faceimage",
    "frame",
    "image_url",
    "imageurl",
    "image",
    "media",
    "media_url",
    "mediaurl",
    "org_id",
    "pcm",
    "preview_image",
    "raw_audio",
    "rawaudio",
    "raw_image",
    "rawimage",
    "url",
    "waveform",
}


def _model_dump(model: BaseModel) -> dict[str, Any]:
    """Return a Pydantic model as a plain dictionary across supported versions."""
    dump = getattr(model, "model_dump", None)
    return dump() if callable(dump) else model.dict()


class StrictRequest(BaseModel):
    """Base class for strict HTTP request shapes."""

    if ConfigDict is not None:
        model_config = ConfigDict(extra="forbid")
    else:  # pragma: no cover - Pydantic v1 compatibility
        class Config:
            extra = "forbid"


def _reject_raw_media_keys(value: Any) -> Any:
    """Reject raw-media and out-of-scope fields in API request metadata/evidence."""
    if isinstance(value, dict):
        for key, item in value.items():
            rendered = str(key or "").strip().casefold()
            if rendered in RAW_MEDIA_KEYS:
                raise ValueError(f"raw media field is not allowed: {key}")
            _reject_raw_media_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_raw_media_keys(item)
    return value


def _validate_embedding(value: list[float]) -> list[float]:
    """Return a finite numeric embedding vector."""
    vector = [float(item) for item in value]
    if not vector:
        raise ValueError("embedding is required")
    if any(not math.isfinite(item) for item in vector):
        raise ValueError("embedding values must be finite")
    return vector


class PersonContextRequest(StrictRequest):
    """Request body for prompt-ready person context."""

    person_id: str
    limit: int = 10
    semantic_scope: str | None = None
    current_text: str | None = None
    now: datetime | None = None
    memory_limit: int = 12
    recent_episode_limit: int = 5


class PersonContextResponse(StrictRequest):
    """Prompt-ready markdown context response."""

    person_id: str
    context_markdown: str
    generated_at: str | None = None


class EpisodeRecordRequest(StrictRequest):
    """Request body for recording one episode."""

    episode: "EpisodePayload"
    extract_memory: bool = True
    enqueue_memory_extraction: bool = True


class SemanticSearchRequest(StrictRequest):
    """Request body for per-person semantic memory search."""

    text: str
    person_id: str
    building_code: str | None = None
    limit: int = 5
    now: datetime | None = None


class PersonPayload(StrictRequest):
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


class PlacePayload(StrictRequest):
    """HTTP shape for PlaceInput."""

    building_code: str
    room_id: str


class EpisodeMentionPayload(StrictRequest):
    """HTTP shape for EpisodeMentionInput."""

    person: PersonPayload
    source: str = "caller"


class EpisodePayload(StrictRequest):
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


class PersonUpsertRequest(StrictRequest):
    """Request body for creating or updating a person."""

    person: PersonPayload


class PersonArchiveRequest(StrictRequest):
    """Request body for archiving a person."""

    person_id: str


class PersonRekeyByEmailRequest(StrictRequest):
    """Request body for email-based person rekeying."""

    email: str = Field(..., min_length=1)
    new_person_id: str = Field(..., min_length=1)


class PersonProfileRequest(StrictRequest):
    """Request body for retrieving one person profile."""

    person_id: str = Field(..., min_length=1)


class IdentityResolveRequest(StrictRequest):
    """Request body for resolving a shared employee identity."""

    shared_first_name: str
    shared_last_name: str
    shared_name: str = ""
    site_code: str = ""


class VerifiedProfileRequest(StrictRequest):
    """Request body for retrieving a verified directory profile."""

    username: str
    official_name: str
    site_code: str = ""


class BiometricSearchRequest(StrictRequest):
    """Request body for biometric reference search."""

    embedding: list[float] = Field(..., min_length=1)
    limit: int = Field(default=2, ge=1, le=20)
    site_code: str | None = None

    @field_validator("embedding")
    def embedding_is_finite(cls, value: list[float]) -> list[float]:
        return _validate_embedding(value)


class BiometricEnrollmentRequest(StrictRequest):
    """Request body for enrolling one biometric reference."""

    person_id: str = Field(..., min_length=1)
    embedding: list[float] = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    consent_status: str = "consented"

    @field_validator("embedding")
    def embedding_is_finite(cls, value: list[float]) -> list[float]:
        return _validate_embedding(value)

    @field_validator("metadata")
    def metadata_has_no_raw_media(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_raw_media_keys(dict(value or {}))


class BiometricObservationRequest(StrictRequest):
    """Request body for adaptive biometric reference update."""

    person_id: str = Field(..., min_length=1)
    embedding: list[float] = Field(..., min_length=1)
    evidence: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("embedding")
    def embedding_is_finite(cls, value: list[float]) -> list[float]:
        return _validate_embedding(value)

    @field_validator("evidence")
    def evidence_has_no_raw_media(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_raw_media_keys(dict(value or {}))

    @field_validator("metadata")
    def metadata_has_no_raw_media(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_raw_media_keys(dict(value or {}))


class VoiceReferenceExistsRequest(StrictRequest):
    """Request body for checking whether a person has a voice reference."""

    person_id: str = Field(..., min_length=1)


class BiometricCandidatePayload(StrictRequest):
    """Reduced biometric candidate shape for turn ownership policy."""

    person_id: str = Field(..., min_length=1)
    display_name: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    def score_is_finite(cls, value: float) -> float:
        rendered = float(value)
        if not math.isfinite(rendered):
            raise ValueError("score must be finite")
        return rendered

    @field_validator("metadata")
    def metadata_has_no_raw_media(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_raw_media_keys(dict(value or {}))


class TurnOwnerResolveRequest(StrictRequest):
    """Request body for resolving a turn owner from reduced identity evidence."""

    primary_face_candidate: BiometricCandidatePayload | None = None
    visible_face_candidates: list[BiometricCandidatePayload] = Field(default_factory=list)
    voice_candidate: BiometricCandidatePayload | None = None
    policy_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("policy_context")
    def policy_context_has_no_raw_media(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _reject_raw_media_keys(dict(value or {}))
