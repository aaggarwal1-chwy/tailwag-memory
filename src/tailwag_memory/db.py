from __future__ import annotations

from typing import Any, Protocol

from .config import Settings


class QueryRunner(Protocol):
    """Protocol for executing Cypher queries with parameters."""

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return row dictionaries."""

        ...


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
            notifications_disabled_categories=["UNRECOGNIZED"],
        )

    def close(self) -> None:
        """Close the underlying Neo4j driver."""

        self._driver.close()

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run Cypher in a session and return row dictionaries."""

        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
