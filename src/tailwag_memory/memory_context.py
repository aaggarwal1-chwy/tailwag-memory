from __future__ import annotations

from datetime import datetime, timezone

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .memory_items import MemoryItemService, PINNED_MEMORY_KEYS, followup_is_visible
from .models import MemoryItemResult
from .retrieval import recent_episode_rows_for_person


class PersonMemoryContextService:
    """Build markdown memory context for a person."""

    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider | None = None) -> None:
        """Store dependencies for memory context rendering."""
        self.runner = runner
        self.embeddings = embeddings

    def markdown_for_person(
        self,
        person_id: str,
        *,
        current_text: str | None = None,
        now: datetime | None = None,
        memory_limit: int = 12,
        recent_episode_limit: int = 5,
    ) -> str:
        """Return markdown memory context for a person."""
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
        recent_episodes = self._recent_episode_lines(person_id, recent_episode_limit)
        return format_person_memory_markdown(items, recent_episode_lines=recent_episodes, now=now, limit=memory_limit)

    def _recent_episode_lines(self, person_id: str, limit: int) -> list[str]:
        """Return sanitized recent episode summary lines."""
        rows = recent_episode_rows_for_person(
            self.runner,
            str(person_id or "").strip(),
            max(1, int(limit or 5)),
        )
        lines: list[str] = []
        for row in rows:
            summary = str(row.get("summary") or "").strip()
            if not summary:
                continue
            start_time = str(row.get("start_time") or "").strip()
            prefix = start_time[:10] if len(start_time) >= 10 else start_time
            line = f"{prefix}: {summary}" if prefix else summary
            lines.append(_sanitize_context_line(line))
        return lines


def format_person_memory_markdown(
    items: list[MemoryItemResult],
    *,
    recent_episode_lines: list[str] | None = None,
    now: datetime | None = None,
    limit: int = 12,
) -> str:
    """Format memory items and episodes as markdown context."""
    sections = [
        ("Boundaries", _section_lines(items, "boundary", now=now, limit=limit)),
        ("Preferences", _section_lines(items, "preference", now=now, limit=limit)),
        ("Pets", _section_lines(items, "pet", now=now, limit=limit)),
        ("Facts", _section_lines(items, "fact", now=now, limit=limit)),
        ("Potential Follow-Ups", _section_lines(items, "followup", now=now, limit=limit)),
        ("Recent Episodes", list(recent_episode_lines or [])),
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


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an optional ISO datetime value."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(item: MemoryItemResult, *, now: datetime | None = None) -> bool:
    """Return whether a memory item is expired."""
    expires = _parse_iso(item.expires_at)
    if expires is None:
        return False
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref > expires


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
