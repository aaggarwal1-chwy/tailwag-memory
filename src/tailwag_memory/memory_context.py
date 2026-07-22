from __future__ import annotations

from datetime import datetime

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .memory_item_helpers import _is_expired, _parse_iso
from .memory_items import MemoryItemService, PINNED_MEMORY_KEYS, followup_is_visible
from .models import MemoryItemResult


class PersonMemoryContextService:
    """Build durable memory markdown for a person."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider | None = None) -> None:
        """Store dependencies for durable memory rendering."""
        self.runner = runner
        self.embeddings = embeddings

    def markdown_for_person(
        self,
        person_id: str,
        *,
        current_text: str | None = None,
        now: datetime | None = None,
        memory_limit: int = 12,
    ) -> str:
        """Return durable memory markdown for a person."""
        memory_service = MemoryItemService(self.runner, self.embeddings or _NoopEmbeddingProvider())
        items = memory_service.list_active_items(person_id=person_id, limit=max(memory_limit * 3, 30), now=now)
        if current_text and self.embeddings is not None:
            vector_items = memory_service.vector_search(
                person_id=person_id,
                text=current_text,
                limit=memory_limit,
                now=now,
            )
            items = _merge_items(items, vector_items)
        return format_person_memory_markdown(items, now=now, limit=memory_limit)


def format_person_memory_markdown(
    items: list[MemoryItemResult],
    *,
    now: datetime | None = None,
    limit: int = 12,
) -> str:
    """Format durable memory items as prompt-ready markdown."""
    sections = [
        ("Boundaries", _section_lines(items, "boundary", now=now, limit=limit)),
        ("Preferences", _section_lines(items, "preference", now=now, limit=limit)),
        ("Pets", _section_lines(items, "pet", now=now, limit=limit)),
        ("Facts", _section_lines(items, "fact", now=now, limit=limit)),
        ("Potential Follow-Ups", _section_lines(items, "followup", now=now, limit=limit)),
    ]
    lines = ["[PERSON MEMORY]"]
    for title, values in sections:
        if not values:
            continue
        lines.append(f"{title}:")
        lines.extend(f"- {value}" for value in values)
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) if len(lines) > 1 else ""


def _merge_items(left: list[MemoryItemResult], right: list[MemoryItemResult]) -> list[MemoryItemResult]:
    """Merge memory item lists by id, preferring scored matches."""
    merged: list[MemoryItemResult] = []
    seen: set[str] = set()
    positions: dict[str, int] = {}
    for item in [*left, *right]:
        if item.memory_id in seen:
            if item.score is not None:
                merged[positions[item.memory_id]] = item
            continue
        positions[item.memory_id] = len(merged)
        merged.append(item)
        seen.add(item.memory_id)
    return merged


def _section_lines(
    items: list[MemoryItemResult],
    kind: str,
    *,
    now: datetime | None,
    limit: int,
) -> list[str]:
    """Return visible sanitized lines for one memory kind."""
    lines: list[str] = []
    for item in _ordered_items(items, kind):
        if kind == "followup":
            if not followup_is_visible(item, now=now):
                continue
        elif item.status != "active" or _is_expired(item, now=now):
            continue
        text = _sanitize_context_line(item.summary)
        if text and text not in lines:
            lines.append(text)
        if len(lines) >= max(1, limit):
            break
    return lines


def _ordered_items(items: list[MemoryItemResult], kind: str) -> list[MemoryItemResult]:
    """Return memory items ordered for context display."""
    filtered = [item for item in items if item.kind == kind]
    if kind == "preference":
        return sorted(
            filtered,
            key=lambda item: (
                item.key not in PINNED_MEMORY_KEYS,
                item.score is None,
                -(item.score or 0.0),
                -_observed_timestamp(item.observed_at),
            ),
        )
    return sorted(
        filtered,
        key=lambda item: (item.score is None, -(item.score or 0.0), -_observed_timestamp(item.observed_at)),
    )


def _observed_timestamp(value: str) -> float:
    """Return an observed timestamp suitable for sorting."""
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed is not None else 0.0


def _sanitize_context_line(value: str) -> str:
    """Normalize a line for markdown context output."""
    rendered = " ".join(str(value or "").split())
    return rendered.lstrip("#-*[]>` ").strip()


class _NoopEmbeddingProvider(EmbeddingProvider):
    """Placeholder embedding provider for non-vector context paths."""

    def embed(self, text: str) -> list[float]:
        """Raise because vector search needs real embeddings."""
        del text
        raise ValueError("An embedding provider is required for vector memory item search.")
