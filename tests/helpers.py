from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
