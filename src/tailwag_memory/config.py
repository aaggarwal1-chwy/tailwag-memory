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
    embedding_model: str = "text-embedding-3-small"
    openai_api_key: str | None = None
    synthesis_model: str = "gpt-5.5"
    slack_bot_token: str | None = None


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


def load_settings() -> Settings:
    """Load runtime settings from .env and process environment."""

    load_env_file()
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "tailwag-memory"),
        embedding_dimension=parse_positive_int_env("TAILWAG_EMBEDDING_DIMENSION", 64),
        embedding_model=os.getenv("TAILWAG_EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        synthesis_model=os.getenv("TAILWAG_SYNTHESIS_MODEL", "gpt-5.5"),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN"),
    )


def load_env_file(path: Path = Path(".env")) -> None:
    """Populate unset environment variables from a simple .env file."""

    if not path.exists():
        return

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
