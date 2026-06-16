from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings


class QueryRunner(Protocol):
    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


@dataclass
class RecordedQuery:
    query: str
    parameters: dict[str, Any]


class RecordingQueryRunner:
    """Test helper that records Cypher without requiring Neo4j."""

    def __init__(self, results: list[list[dict[str, Any]]] | None = None) -> None:
        self.queries: list[RecordedQuery] = []
        self._results = results or []

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append(RecordedQuery(query=query, parameters=parameters or {}))
        if self._results:
            return self._results.pop(0)
        return []


class Neo4jQueryRunner:
    def __init__(self, settings: Settings) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Install the neo4j package to use Neo4jQueryRunner.") from exc

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
