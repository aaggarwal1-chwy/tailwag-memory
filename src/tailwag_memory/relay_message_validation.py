"""Validation helpers for robot relay messages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from .config import Settings
from .models import RelayMessageInput

_FORBIDDEN_METADATA_KEYS = {
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
    "image",
    "image_url",
    "imageurl",
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
    "voice_embedding",
    "waveform",
}
_MAX_METADATA_JSON_CHARACTERS = 4096


def default_settings() -> Settings:
    """Build the minimal settings used when a runner does not expose them."""
    return Settings(
        neo4j_uri="",
        neo4j_user="",
        neo4j_password="",
        embedding_dimension=64,
    )


def required(value: str, name: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise ValueError(f"{name} is required")
    return rendered


def email(value: str) -> str:
    rendered = required(value, "email").lower()
    if len(rendered) > 320:
        raise ValueError("email must be at most 320 characters")
    if rendered.count("@") != 1 or rendered.startswith("@") or rendered.endswith("@"):
        raise ValueError("email must be a valid unique identifier")
    return rendered


def parse_timestamp(value: str, name: str) -> datetime:
    try:
        rendered = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(rendered)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("relay clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def validate_input(
    message: RelayMessageInput,
    *,
    robot_id: str,
    settings: Settings,
    now: datetime,
) -> RelayMessageInput:
    """Validate and normalize a caller-provided relay message."""
    required(robot_id, "robot_id")
    message_id = required(message.id, "id")
    if len(message_id) > 128:
        raise ValueError("id must be at most 128 characters")
    if len(str(robot_id)) > 128:
        raise ValueError("robot_id must be at most 128 characters")
    sender_email = email(message.sender_email)
    recipient_email = email(message.recipient_email)
    if sender_email == recipient_email:
        raise ValueError("sender and recipient must be different people")
    if not message.body.strip():
        raise ValueError("body is required")
    if len(message.body) > settings.relay_max_body_characters:
        raise ValueError(
            f"body must be at most {settings.relay_max_body_characters} characters"
        )
    deliver_after = (
        parse_timestamp(message.deliver_after, "deliver_after")
        if message.deliver_after
        else now
    )
    expires_at = (
        parse_timestamp(message.expires_at, "expires_at")
        if message.expires_at
        else now + timedelta(days=settings.relay_default_expiry_days)
    )
    maximum_expiry = now + timedelta(days=settings.relay_default_expiry_days)
    if expires_at > maximum_expiry:
        raise ValueError(
            f"expires_at may not be more than {settings.relay_default_expiry_days} days away"
        )
    if expires_at <= now:
        raise ValueError("expires_at must be in the future")
    if deliver_after >= expires_at:
        raise ValueError("deliver_after must be before expires_at")
    if not isinstance(message.metadata, dict):
        raise ValueError("metadata must be an object")
    if _contains_forbidden_metadata(message.metadata):
        raise ValueError("metadata must not contain raw media, embeddings, URLs, or org_id")
    try:
        metadata_json = json.dumps(
            message.metadata,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    if len(metadata_json) > _MAX_METADATA_JSON_CHARACTERS:
        raise ValueError(
            f"metadata JSON must be at most {_MAX_METADATA_JSON_CHARACTERS} characters"
        )
    return RelayMessageInput(
        id=message_id,
        sender_email=sender_email,
        recipient_email=recipient_email,
        body=message.body,
        deliver_after=deliver_after.isoformat(),
        expires_at=expires_at.isoformat(),
        metadata=dict(message.metadata),
    )


def _contains_forbidden_metadata(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key or "").strip().casefold().replace("-", "_")
            if normalized in _FORBIDDEN_METADATA_KEYS:
                return True
            if _contains_forbidden_metadata(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_metadata(item) for item in value)
    return False
