from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    embedding_dimension: int


def load_settings() -> Settings:
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "tailwag-memory"),
        embedding_dimension=int(os.getenv("TAILWAG_EMBEDDING_DIMENSION", "64")),
    )
