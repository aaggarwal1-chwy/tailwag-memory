from __future__ import annotations

from typing import Any, Protocol

from .models import MemoryItemResult


class MemoryExtractionProvider(Protocol):
    """Protocol for transcript-to-memory extraction providers."""

    def extract(
        self,
        *,
        person_id: str,
        target_display_name: str | None = None,
        transcript: str,
        existing_memories: list[MemoryItemResult],
        current_time: str,
    ) -> dict[str, Any]:
        """Return memory operations for one person transcript."""
        ...


class MemoryConsolidationProvider(Protocol):
    """Protocol for person episode clusters-to-memory consolidation providers."""

    def consolidate(
        self,
        *,
        person_id: str,
        existing_memories: list[MemoryItemResult],
        episode_clusters: list[list[dict[str, str]]],
        current_time: str,
        min_evidence_episodes: int,
    ) -> dict[str, Any]:
        """Return memory operations supported by supplied episode clusters."""
        ...
