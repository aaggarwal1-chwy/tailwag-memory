from __future__ import annotations

from datetime import datetime
import re

from .db import QueryRunner
from .embeddings import EmbeddingProvider
from .memory_item_helpers import _is_expired, _parse_iso
from .memory_items import MemoryItemService, PINNED_MEMORY_KEYS, followup_is_visible
from .models import MemoryItemResult
from .retrieval import recent_episode_rows_for_person


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
        recent_episode_limit: int = 5,
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
        recent_episodes = self._recent_episode_lines(person_id, recent_episode_limit)
        return format_person_memory_markdown(items, recent_episode_lines=recent_episodes, now=now, limit=memory_limit)

    def _recent_episode_lines(self, person_id: str, limit: int) -> list[str]:
        """Return sanitized recent episode transcript lines."""
        rows = recent_episode_rows_for_person(
            self.runner,
            str(person_id or "").strip(),
            max(1, int(limit or 5)),
        )
        lines: list[str] = []
        for row in rows:
            transcript = str(row.get("transcript") or "").strip()
            if not transcript:
                continue
            speech_lines = _target_speech_lines(
                transcript,
                person_id=str(row.get("person_id") or person_id or ""),
                display_name=str(row.get("display_name") or ""),
                speaker_labels=_row_speaker_labels(row),
            )
            if not speech_lines:
                continue
            start_time = str(row.get("start_time") or "").strip()
            prefix = start_time[:10] if len(start_time) >= 10 else start_time
            rendered = " ".join(speech_lines)
            line = f"{prefix}: {rendered}" if prefix else rendered
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


def _target_speech_lines(
    transcript: str,
    *,
    person_id: str,
    display_name: str,
    speaker_labels: list[str],
) -> list[str]:
    """Return transcript lines whose speaker matches the target person."""
    labels = {
        _normalize_speaker_label(label)
        for label in [display_name, person_id]
        if _normalize_speaker_label(label)
    }
    if not labels:
        return []

    turn_labels = _speaker_label_pattern([*speaker_labels, display_name, person_id, "Assistant", "User"])
    if turn_labels is None:
        return []

    lines: list[str] = []
    for raw_line in transcript.splitlines():
        matches = list(turn_labels.finditer(raw_line))
        for index, match in enumerate(matches):
            speaker = match.group("speaker").strip()
            if _normalize_speaker_label(speaker) not in labels:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_line)
            text = raw_line[match.end() : end].strip()
            if text:
                lines.append(f"{speaker}: {text}")
    return lines


def _normalize_speaker_label(value: str) -> str:
    """Normalize a transcript speaker label for exact target matching."""
    return " ".join(str(value or "").strip().casefold().split())


def _row_speaker_labels(row: dict[str, object]) -> list[str]:
    """Return known episode speaker labels from a retrieval row."""
    raw_labels = row.get("speaker_labels")
    if not isinstance(raw_labels, list):
        return []
    return [str(label) for label in raw_labels if str(label or "").strip()]


def _speaker_label_pattern(labels: list[str]) -> re.Pattern[str] | None:
    """Build a speaker-turn matcher from known labels."""
    normalized: dict[str, str] = {}
    for label in labels:
        rendered = str(label or "").strip()
        if not rendered:
            continue
        normalized.setdefault(_normalize_speaker_label(rendered), rendered)
    if not normalized:
        return None
    choices = "|".join(re.escape(label) for label in sorted(normalized.values(), key=len, reverse=True))
    return re.compile(rf"(?:^|\s)(?:\[[^\]]+\]\s*)?(?P<speaker>{choices}):\s*")


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
