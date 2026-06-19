from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .memory_item_constants import (
    DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
    IDENTITY_OWNED_PREFIXES,
    MEMORY_ITEM_KINDS,
    MEMORY_ITEM_SOURCES,
    MEMORY_ITEM_STATUSES,
    TRANSIENT_TASK_MARKERS,
    TRANSIENT_TASK_TOPICS,
)
from .models import MemoryItemInput, MemoryItemResult, utc_now_iso


_PRESERVE = object()


@dataclass(frozen=True)
class _EpisodeEvidence:
    """Episode evidence available to a consolidation provider."""

    episode_id: str
    summary: str
    transcript: str
    start_time: str
    end_time: str = ""
    score: float | None = None


def normalize_memory_key(value: Any) -> str:
    """Normalize a memory key for deterministic storage."""
    rendered = str(value or "").strip().casefold()
    normalized = "".join(char if char.isalnum() else "_" for char in rendered)
    return "_".join(part for part in normalized.split("_") if part)


def normalize_memory_source(value: Any) -> str:
    """Normalize a memory item source to an allowed value."""
    source = str(value or "").strip()
    return source if source in MEMORY_ITEM_SOURCES else "caller"


def stable_memory_id(*, person_id: str, kind: str, key: str) -> str:
    """Return the deterministic memory id for a person item."""
    seed = "|".join([person_id, kind, key]).encode("utf-8")
    return f"mem_{hashlib.sha256(seed).hexdigest()[:32]}"


def _json_dumps(value: Any) -> str:
    """Serialize metadata as deterministic JSON."""
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=True, sort_keys=True)


def _json_loads(value: Any) -> dict[str, Any]:
    """Deserialize metadata JSON into a dictionary."""
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _unique_nonempty(values: list[str] | tuple[str, ...]) -> list[str]:
    """Return nonempty strings once, preserving first-seen order."""
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or "").strip()
        if rendered and rendered not in seen:
            unique.append(rendered)
            seen.add(rendered)
    return unique


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


def _now(value: datetime | None = None) -> datetime:
    """Return a timezone-aware reference datetime."""
    ref = value or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        return ref.replace(tzinfo=timezone.utc)
    return ref


def followup_is_visible(item: MemoryItemResult, *, now: datetime | None = None) -> bool:
    """Return whether an active follow-up should be shown."""
    if item.kind != "followup" or item.status != "active":
        return False
    expires = _parse_iso(item.expires_at)
    if expires is None:
        return False
    due = _parse_iso(item.due_at)
    ref = _now(now)
    if due is not None and ref < due:
        return False
    return ref <= expires


def _is_expired(item: MemoryItemResult, *, now: datetime | None = None) -> bool:
    """Return whether a memory item has expired."""
    expires = _parse_iso(item.expires_at)
    return expires is not None and _now(now) > expires


def _summary_has_identity_owned_prefix(summary: str) -> bool:
    """Return whether a summary starts with directory-owned data."""
    lowered = summary.strip().casefold()
    return any(lowered.startswith(prefix) for prefix in IDENTITY_OWNED_PREFIXES)


def _looks_like_transient_task_status(summary: str) -> bool:
    """Return whether summary describes a short-lived task better stored as a follow-up."""
    lowered = summary.strip().casefold()
    return any(marker in lowered for marker in TRANSIENT_TASK_MARKERS) and any(
        topic in lowered for topic in TRANSIENT_TASK_TOPICS
    )


def _validate_memory_fields(
    *,
    kind: str,
    status: str,
    summary: str,
    observed_at: str,
    due_at: str,
    expires_at: str,
    require_followup_expiry: bool,
) -> None:
    """Validate shared memory item field rules."""
    if not summary:
        raise ValueError("memory item summary is required")
    if _summary_has_identity_owned_prefix(summary):
        raise ValueError("identity-owned directory facts do not belong in memory items")
    if kind != "followup" and _looks_like_transient_task_status(summary):
        raise ValueError("transient task status belongs in a followup memory item")
    if status not in MEMORY_ITEM_STATUSES:
        raise ValueError(f"invalid memory item status: {status!r}")
    if observed_at and _parse_iso(observed_at) is None:
        raise ValueError("observed_at must be an ISO datetime")
    if due_at and _parse_iso(due_at) is None:
        raise ValueError("due_at must be an ISO datetime")
    if expires_at and _parse_iso(expires_at) is None:
        raise ValueError("expires_at must be an ISO datetime")
    if kind == "followup" and require_followup_expiry and not expires_at:
        raise ValueError("followup memory items require expires_at")


def _validate_item(item: MemoryItemInput) -> MemoryItemInput:
    """Validate and normalize a memory item input."""
    kind = str(item.kind or "").strip()
    source = str(item.source or "").strip()
    status = str(item.status or "").strip()
    key = normalize_memory_key(item.key)
    summary = str(item.summary or "").strip()
    if kind not in MEMORY_ITEM_KINDS:
        raise ValueError(f"invalid memory item kind: {item.kind!r}")
    if source not in MEMORY_ITEM_SOURCES:
        raise ValueError(f"invalid memory item source: {item.source!r}")
    if not key:
        raise ValueError("memory item key is required")
    _validate_memory_fields(
        kind=kind,
        status=status,
        summary=summary,
        observed_at=str(item.observed_at or "").strip(),
        due_at=str(item.due_at or "").strip(),
        expires_at=str(item.expires_at or "").strip(),
        require_followup_expiry=True,
    )
    return replace(
        item,
        kind=kind,
        key=key,
        summary=summary,
        source=source,
        status=status,
        source_ref=str(item.source_ref or "").strip(),
        observed_at=str(item.observed_at or "").strip(),
        due_at=str(item.due_at or "").strip(),
        expires_at=str(item.expires_at or "").strip(),
        metadata=dict(item.metadata or {}),
    )


def _validate_update_fields(item: MemoryItemInput) -> None:
    """Validate fields allowed during memory item updates."""
    summary = str(item.summary or "").strip()
    status = str(item.status or "").strip()
    _validate_memory_fields(
        kind=str(item.kind or "").strip(),
        status=status,
        summary=summary,
        observed_at=str(item.observed_at or "").strip(),
        due_at=str(item.due_at or "").strip(),
        expires_at=str(item.expires_at or "").strip(),
        require_followup_expiry=False,
    )
    if item.kind == "followup" and status == "active" and not item.expires_at:
        raise ValueError("active followup memory items require expires_at")


def _tokenize(text: str) -> set[str]:
    """Return coarse tokens for transcript-memory matching."""
    normalized = "".join(char.casefold() if char.isalnum() else " " for char in str(text or ""))
    return {part for part in normalized.split() if len(part) >= 3}


def _operation_metadata(raw: dict[str, Any], *, default: dict[str, Any] | object) -> dict[str, Any] | object:
    """Extract and validate metadata from an operation payload."""
    if "metadata" not in raw:
        return default
    value = raw.get("metadata")
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("memory operation metadata must be an object")
    return dict(value)

def _consolidation_metadata(raw: dict[str, Any], *, default: dict[str, Any] | object) -> dict[str, Any] | object:
    """Return consolidation metadata only when it is the strict empty object."""
    if "metadata" not in raw:
        return default
    value = raw.get("metadata")
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("memory consolidation metadata must be an object")
    raise ValueError("memory consolidation metadata must be empty")


def _validated_support_ids(
    raw: dict[str, Any],
    *,
    evidence_by_id: dict[str, _EpisodeEvidence],
    skipped: list[Any],
) -> list[str]:
    """Return unique support IDs that were fetched as person-scoped evidence."""
    raw_ids = raw.get("supported_episode_ids")
    if not isinstance(raw_ids, list):
        return []
    support: list[str] = []
    for episode_id in _unique_nonempty([str(value or "") for value in raw_ids]):
        if episode_id not in evidence_by_id:
            skipped.append({"reason": "unsupported_episode_id", "episode_id": episode_id, "op": raw})
            continue
        support.append(episode_id)
    return support


def _row_to_episode_evidence(row: dict[str, Any]) -> _EpisodeEvidence:
    """Convert a Neo4j row into episode evidence."""
    score = row.get("score")
    return _EpisodeEvidence(
        episode_id=str(row.get("episode_id") or ""),
        summary=str(row.get("summary") or ""),
        transcript=str(row.get("transcript") or ""),
        start_time=str(row.get("start_time") or ""),
        end_time=str(row.get("end_time") or ""),
        score=score if isinstance(score, float) else None,
    )


def _dedupe_episode_evidence(episodes: list[_EpisodeEvidence]) -> list[_EpisodeEvidence]:
    """Return evidence episodes once, preserving first-seen order."""
    selected: list[_EpisodeEvidence] = []
    seen: set[str] = set()
    for episode in episodes:
        if not episode.episode_id or episode.episode_id in seen:
            continue
        selected.append(episode)
        seen.add(episode.episode_id)
    return selected


def _episode_evidence_payload(episode: _EpisodeEvidence, *, text_limit: int) -> dict[str, str]:
    """Render bounded evidence for consolidation provider input."""
    limit = _positive_int(text_limit, DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT)
    return {
        "episode_id": episode.episode_id,
        "summary": episode.summary[:limit],
        "transcript": episode.transcript[:limit],
        "start_time": episode.start_time,
        "end_time": episode.end_time,
    }


def _latest_episode_time(support: list[str], evidence_by_id: dict[str, _EpisodeEvidence]) -> str:
    """Return the latest available start time from supporting evidence."""
    times = [evidence_by_id[episode_id].start_time for episode_id in support if evidence_by_id[episode_id].start_time]
    return max(times) if times else utc_now_iso()


def _positive_int(value: int, default: int) -> int:
    """Return a positive integer or a default."""
    try:
        rendered = int(value)
    except Exception:
        return default
    return rendered if rendered > 0 else default
