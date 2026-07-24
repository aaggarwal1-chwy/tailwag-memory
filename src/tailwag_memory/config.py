from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment values."""

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    embedding_dimension: int
    face_embedding_dimension: int = 512
    voice_embedding_dimension: int = 192
    embedding_model: str = "text-embedding-3-small"
    face_embedding_model: str = "facenet"
    voice_embedding_model: str = "speechbrain_ecapa"
    openai_api_key: str | None = None
    synthesis_model: str = "gpt-5.5"
    slack_bot_token: str | None = None
    affect_fold1_model: str | None = None
    affect_fold2_model: str | None = None
    relay_default_expiry_days: int = 30
    relay_max_body_characters: int = 500
    relay_max_pending_per_pair: int = 3
    relay_max_sends_per_sender_per_day: int = 5
    relay_policy_model: str = "gpt-5.5"
    relay_policy_timeout_seconds: int = 8
    relay_policy_max_retries: int = 1


def parse_positive_int_env(name: str, default: int) -> int:
    """Read a positive integer environment variable with a default."""

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def parse_bounded_int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read an integer environment variable constrained to a safe range."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be between {minimum} and {maximum}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def load_settings() -> Settings:
    """Load runtime settings from .env and process environment."""

    load_env_file()
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "tailwag-memory"),
        embedding_dimension=parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64),
        face_embedding_dimension=parse_positive_int_env("TAILWAG_FACE_EMBEDDING_DIMENSION", 512),
        voice_embedding_dimension=parse_positive_int_env("TAILWAG_VOICE_EMBEDDING_DIMENSION", 192),
        embedding_model=os.getenv("TAILWAG_EMBEDDING_MODEL", "text-embedding-3-small"),
        face_embedding_model=_optional_env("TAILWAG_FACE_EMBEDDING_MODEL") or "facenet",
        voice_embedding_model=_optional_env("TAILWAG_VOICE_EMBEDDING_MODEL") or "speechbrain_ecapa",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        synthesis_model=os.getenv("TAILWAG_SYNTHESIS_MODEL", "gpt-5.5"),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN"),
        affect_fold1_model=_optional_env("TAILWAG_AFFECT_FOLD1_MODEL"),
        affect_fold2_model=_optional_env("TAILWAG_AFFECT_FOLD2_MODEL"),
        relay_default_expiry_days=parse_positive_int_env("TAILWAG_RELAY_DEFAULT_EXPIRY_DAYS", 30),
        relay_max_body_characters=parse_positive_int_env("TAILWAG_RELAY_MAX_BODY_CHARACTERS", 500),
        relay_max_pending_per_pair=parse_positive_int_env("TAILWAG_RELAY_MAX_PENDING_PER_PAIR", 3),
        relay_max_sends_per_sender_per_day=parse_positive_int_env(
            "TAILWAG_RELAY_MAX_SENDS_PER_SENDER_PER_DAY",
            5,
        ),
        relay_policy_model=os.getenv("TAILWAG_RELAY_POLICY_MODEL", "gpt-5.5"),
        relay_policy_timeout_seconds=parse_bounded_int_env(
            "TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS",
            8,
            minimum=1,
            maximum=10,
        ),
        relay_policy_max_retries=parse_bounded_int_env(
            "TAILWAG_RELAY_POLICY_MAX_RETRIES",
            1,
            minimum=0,
            maximum=1,
        ),
    )


def validate_relay_settings(settings: Settings) -> None:
    """Fail fast when relay policy configuration is incomplete or unsafe."""
    positive_fields = {
        "TAILWAG_RELAY_DEFAULT_EXPIRY_DAYS": settings.relay_default_expiry_days,
        "TAILWAG_RELAY_MAX_BODY_CHARACTERS": settings.relay_max_body_characters,
        "TAILWAG_RELAY_MAX_PENDING_PER_PAIR": settings.relay_max_pending_per_pair,
        "TAILWAG_RELAY_MAX_SENDS_PER_SENDER_PER_DAY": (
            settings.relay_max_sends_per_sender_per_day
        ),
    }
    for name, value in positive_fields.items():
        if value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not str(settings.openai_api_key or "").strip():
        raise ValueError("OPENAI_API_KEY is required for relay safety screening")
    if not str(settings.relay_policy_model or "").strip():
        raise ValueError("TAILWAG_RELAY_POLICY_MODEL is required")
    if settings.relay_policy_timeout_seconds < 1 or settings.relay_policy_timeout_seconds > 10:
        raise ValueError("TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS must be between 1 and 10")
    if settings.relay_policy_max_retries < 0 or settings.relay_policy_max_retries > 1:
        raise ValueError("TAILWAG_RELAY_POLICY_MAX_RETRIES must be between 0 and 1")


def load_env_file(path: Path = Path(".env")) -> None:
    """Populate unset environment variables from a simple .env file."""

    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _optional_env(name: str) -> str | None:
    """Return a stripped optional environment value."""
    value = os.getenv(name)
    if value is None:
        return None
    rendered = value.strip()
    return rendered or None
