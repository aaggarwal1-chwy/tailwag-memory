from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings


class QueryRunner(Protocol):
    """Protocol for executing Cypher queries with parameters."""

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return row dictionaries."""

        ...


@dataclass
class RecordedQuery:
    """Captured Cypher query and parameters for test assertions."""

    query: str
    parameters: dict[str, Any]


class RecordingQueryRunner:
    """Test helper that records Cypher without requiring Neo4j."""

    def __init__(self, results: list[list[dict[str, Any]]] | None = None) -> None:
        """Initialize the recorder with optional queued result sets."""

        self.queries: list[RecordedQuery] = []
        self._results = results or []

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Record a query and return the next queued result set."""

        self.queries.append(RecordedQuery(query=query, parameters=parameters or {}))
        if self._results:
            return self._results.pop(0)
        return []


class Neo4jQueryRunner:
    """Query runner backed by a Neo4j driver session."""

    def __init__(self, settings: Settings) -> None:
        """Create a Neo4j driver from runtime settings."""

        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Install the neo4j package to use Neo4jQueryRunner.") from exc

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        """Close the underlying Neo4j driver."""

        self._driver.close()

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run Cypher in a session and return row dictionaries."""

        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
