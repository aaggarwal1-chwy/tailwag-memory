from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol

from .db import QueryRunner
from .embeddings import EmbeddingProvider, OpenAIConfigurationError
from .models import (
    EpisodeInput,
    EpisodeMemoryExtractionResult,
    MemoryItemInput,
    MemoryItemResult,
    PersonInput,
    PersonMemoryExtractionResult,
    PlaceInput,
    utc_now_iso,
)


MEMORY_ITEM_KINDS = {"preference", "boundary", "pet", "fact", "followup"}
MEMORY_ITEM_SOURCES = {"caller", "calling-system", "live_chat", "slack", "argos"}
MEMORY_ITEM_STATUSES = {"active", "archived", "superseded"}
PINNED_MEMORY_KEYS = {"preferred_name", "preferred_language", "nickname_for_robot", "birthday"}
_PRESERVE = object()
IDENTITY_OWNED_PREFIXES = (
    "team:",
    "title:",
    "business title:",
    "tenure:",
    "manager:",
    "manager name:",
    "cost center:",
    "business function:",
    "leadership org:",
    "senior leadership team:",
    "job family:",
    "job level:",
    "c level:",
)
MEMORY_EXTRACTION_TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "memory_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "update": {"type": "boolean"},
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "op": {"type": "string", "enum": ["create", "update", "archive", "noop"]},
                            "memory_id": {"type": "string"},
                            "kind": {"type": "string", "enum": ["preference", "boundary", "pet", "fact", "followup"]},
                            "key": {"type": "string"},
                            "summary": {"type": "string"},
                            "observed_at": {"type": "string"},
                            "due_at": {"type": "string"},
                            "expires_at": {"type": "string"},
                            "metadata": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {},
                                "required": [],
                            },
                        },
                        "required": [
                            "op",
                            "memory_id",
                            "kind",
                            "key",
                            "summary",
                            "observed_at",
                            "due_at",
                            "expires_at",
                            "metadata",
                        ],
                    },
                },
            },
            "required": ["update", "ops"],
        },
    }
}


class MemoryExtractionProvider(Protocol):
    def extract(
        self,
        *,
        person_id: str,
        target_display_name: str | None = None,
        transcript: str,
        existing_memories: list[MemoryItemResult],
        current_time: str,
    ) -> dict[str, Any]:
        ...


def normalize_memory_key(value: Any) -> str:
    rendered = str(value or "").strip().casefold()
    normalized = "".join(char if char.isalnum() else "_" for char in rendered)
    return "_".join(part for part in normalized.split("_") if part)


def normalize_memory_source(value: Any) -> str:
    source = str(value or "").strip()
    return source if source in MEMORY_ITEM_SOURCES else "caller"


def stable_memory_id(*, person_id: str, kind: str, key: str) -> str:
    seed = "|".join([person_id, kind, key]).encode("utf-8")
    return f"mem_{hashlib.sha256(seed).hexdigest()[:32]}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=True, sort_keys=True)


def _json_loads(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_iso(value: str | None) -> datetime | None:
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
    ref = value or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        return ref.replace(tzinfo=timezone.utc)
    return ref


def followup_is_visible(item: MemoryItemResult, *, now: datetime | None = None) -> bool:
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
    expires = _parse_iso(item.expires_at)
    return expires is not None and _now(now) > expires


def _summary_has_identity_owned_prefix(summary: str) -> bool:
    lowered = summary.strip().casefold()
    return any(lowered.startswith(prefix) for prefix in IDENTITY_OWNED_PREFIXES)


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
    if not summary:
        raise ValueError("memory item summary is required")
    if _summary_has_identity_owned_prefix(summary):
        raise ValueError("identity-owned directory facts do not belong in memory items")
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


class MemoryItemService:
    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider) -> None:
        self.runner = runner
        self.embeddings = embeddings

    def upsert_item(
        self,
        *,
        person_id: str,
        item: MemoryItemInput,
        supported_by_episode_id: str | None = None,
    ) -> str:
        rendered_person_id = str(person_id or "").strip()
        if not rendered_person_id:
            raise ValueError("person_id is required")
        validated = _validate_item(item)
        expected_memory_id = stable_memory_id(
            person_id=rendered_person_id,
            kind=validated.kind,
            key=validated.key,
        )
        memory_id = (validated.memory_id or expected_memory_id).strip()
        if memory_id != expected_memory_id:
            raise ValueError("memory_id must be the deterministic person/kind/key memory id")
        now = utc_now_iso()
        observed_at = validated.observed_at or now
        self.runner.run(
            """
            MERGE (p:Person {id: $person_id})
            MERGE (m:MemoryItem {id: $memory_id})
            SET m.kind = $kind,
                m.key = $key,
                m.summary = $summary,
                m.summary_embedding = $summary_embedding,
                m.source = $source,
                m.source_ref = $source_ref,
                m.status = $status,
                m.observed_at = $observed_at,
                m.due_at = $due_at,
                m.expires_at = $expires_at,
                m.metadata_json = $metadata_json,
                m.created_at = coalesce(m.created_at, $now),
                m.updated_at = $now
            MERGE (p)-[:HAS_MEMORY]->(m)
            WITH m
            OPTIONAL MATCH (e:Episode {id: $episode_id})
            FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
              MERGE (m)-[:SUPPORTED_BY]->(e)
            )
            """,
            {
                "person_id": rendered_person_id,
                "memory_id": memory_id,
                "kind": validated.kind,
                "key": validated.key,
                "summary": validated.summary,
                "summary_embedding": self.embeddings.embed(validated.summary),
                "source": validated.source,
                "source_ref": validated.source_ref,
                "status": validated.status,
                "observed_at": observed_at,
                "due_at": validated.due_at,
                "expires_at": validated.expires_at,
                "metadata_json": _json_dumps(validated.metadata),
                "now": now,
                "episode_id": str(supported_by_episode_id or "").strip() or None,
            },
        )
        return memory_id

    def update_item(
        self,
        memory_id: str,
        *,
        summary: str = "",
        source_ref: str | None | object = _PRESERVE,
        status: str | object = _PRESERVE,
        observed_at: str = "",
        due_at: str | object = _PRESERVE,
        expires_at: str | object = _PRESERVE,
        metadata: dict[str, Any] | object = _PRESERVE,
        supported_by_episode_id: str | None = None,
    ) -> bool:
        rendered = str(memory_id or "").strip()
        if not rendered:
            return False
        existing = self.get_item(rendered)
        if existing is None:
            return False
        next_summary = str(summary or "").strip() or existing.summary
        if source_ref is _PRESERVE:
            next_source_ref = existing.source_ref
        elif source_ref is None:
            next_source_ref = ""
        else:
            next_source_ref = str(source_ref).strip()
        next_status = str(status).strip() if status is not _PRESERVE else existing.status
        next_due_at = str(due_at).strip() if due_at is not _PRESERVE else existing.due_at
        next_expires_at = str(expires_at).strip() if expires_at is not _PRESERVE else existing.expires_at
        next_observed_at = str(observed_at or "").strip()
        next_metadata = dict(metadata) if isinstance(metadata, dict) else existing.metadata
        item = MemoryItemInput(
            kind=existing.kind,
            key=existing.key,
            summary=next_summary,
            status=next_status,
            observed_at=next_observed_at,
            due_at=next_due_at,
            expires_at=next_expires_at,
            metadata=next_metadata,
        )
        _validate_update_fields(item)
        rows = self.runner.run(
            """
            MATCH (m:MemoryItem {id: $memory_id})
            SET m.summary = $summary,
                m.summary_embedding = $summary_embedding,
                m.source_ref = $source_ref,
                m.status = $status,
                m.observed_at = coalesce($observed_at, m.observed_at),
                m.due_at = $due_at,
                m.expires_at = $expires_at,
                m.metadata_json = $metadata_json,
                m.updated_at = $now
            WITH m
            OPTIONAL MATCH (e:Episode {id: $episode_id})
            FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
              MERGE (m)-[:SUPPORTED_BY]->(e)
            )
            RETURN m.id AS memory_id
            """,
            {
                "memory_id": rendered,
                "summary": next_summary,
                "summary_embedding": self.embeddings.embed(next_summary),
                "source_ref": next_source_ref,
                "status": next_status,
                "observed_at": next_observed_at or None,
                "due_at": next_due_at,
                "expires_at": next_expires_at,
                "metadata_json": _json_dumps(next_metadata),
                "now": utc_now_iso(),
                "episode_id": str(supported_by_episode_id or "").strip() or None,
            },
        )
        return bool(rows)

    def archive_item(self, memory_id: str) -> bool:
        rendered = str(memory_id or "").strip()
        if not rendered:
            return False
        rows = self.runner.run(
            """
            MATCH (m:MemoryItem {id: $memory_id})
            SET m.status = 'archived',
                m.updated_at = $now
            RETURN m.id AS memory_id
            """,
            {"memory_id": rendered, "now": utc_now_iso()},
        )
        return bool(rows)

    def get_item(self, memory_id: str) -> MemoryItemResult | None:
        rows = self.runner.run(
            """
            MATCH (p:Person)-[:HAS_MEMORY]->(m:MemoryItem {id: $memory_id})
            RETURN p.id AS person_id,
                   m.id AS memory_id,
                   m.kind AS kind,
                   m.key AS key,
                   m.summary AS summary,
                   m.source AS source,
                   m.source_ref AS source_ref,
                   m.status AS status,
                   m.observed_at AS observed_at,
                   m.created_at AS created_at,
                   m.updated_at AS updated_at,
                   m.due_at AS due_at,
                   m.expires_at AS expires_at,
                   m.metadata_json AS metadata_json
            LIMIT 1
            """,
            {"memory_id": str(memory_id or "").strip()},
        )
        return self._row_to_item(rows[0]) if rows else None

    def list_items(
        self,
        *,
        person_id: str,
        kinds: tuple[str, ...] = (),
        statuses: tuple[str, ...] = (),
        source: str = "",
        limit: int = 100,
    ) -> list[MemoryItemResult]:
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE (size($kinds) = 0 OR m.kind IN $kinds)
              AND (size($statuses) = 0 OR m.status IN $statuses)
              AND ($source = '' OR m.source = $source)
            RETURN $person_id AS person_id,
                   m.id AS memory_id,
                   m.kind AS kind,
                   m.key AS key,
                   m.summary AS summary,
                   m.source AS source,
                   m.source_ref AS source_ref,
                   m.status AS status,
                   m.observed_at AS observed_at,
                   m.created_at AS created_at,
                   m.updated_at AS updated_at,
                   m.due_at AS due_at,
                   m.expires_at AS expires_at,
                   m.metadata_json AS metadata_json
            ORDER BY m.observed_at DESC, m.updated_at DESC
            LIMIT $limit
            """,
            {
                "person_id": str(person_id or "").strip(),
                "kinds": list(kinds),
                "statuses": list(statuses),
                "source": str(source or "").strip(),
                "limit": max(1, int(limit or 100)),
            },
        )
        return [self._row_to_item(row) for row in rows]

    def list_active_items(
        self,
        *,
        person_id: str,
        kinds: tuple[str, ...] = (),
        source: str = "",
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryItemResult]:
        requested_limit = max(1, int(limit or 100))
        items = self.list_items(
            person_id=person_id,
            kinds=kinds,
            statuses=("active",),
            source=source,
            limit=max(requested_limit * 5, 100),
        )
        return [item for item in items if not _is_expired(item, now=now)][:requested_limit]

    def vector_search(
        self,
        *,
        person_id: str,
        text: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[MemoryItemResult]:
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:HAS_MEMORY]->(node:MemoryItem)
            WHERE node.status = 'active'
              AND node.summary_embedding IS NOT NULL
            WITH node, vector.similarity.cosine(node.summary_embedding, $embedding) AS score
            RETURN $person_id AS person_id,
                   node.id AS memory_id,
                   node.kind AS kind,
                   node.key AS key,
                   node.summary AS summary,
                   node.source AS source,
                   node.source_ref AS source_ref,
                   node.status AS status,
                   node.observed_at AS observed_at,
                   node.created_at AS created_at,
                   node.updated_at AS updated_at,
                   node.due_at AS due_at,
                   node.expires_at AS expires_at,
                   node.metadata_json AS metadata_json,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {
                "embedding": self.embeddings.embed(text),
                "person_id": str(person_id or "").strip(),
                "limit": max(1, int(limit or 10)),
            },
        )
        return [item for item in (self._row_to_item(row) for row in rows) if not _is_expired(item, now=now)]

    def candidate_items(
        self,
        *,
        person_id: str,
        transcript: str,
        limit: int = 12,
    ) -> list[MemoryItemResult]:
        active = self.list_active_items(person_id=person_id, limit=100)
        selected: list[MemoryItemResult] = []
        seen: set[str] = set()

        def add(item: MemoryItemResult) -> None:
            if item.memory_id in seen or len(selected) >= max(1, limit):
                return
            selected.append(item)
            seen.add(item.memory_id)

        for item in active:
            if item.key in PINNED_MEMORY_KEYS or item.kind in {"boundary", "pet", "followup"}:
                add(item)

        if len(selected) >= max(1, limit):
            return selected

        transcript_tokens = _tokenize(transcript)
        scored: list[tuple[int, str, MemoryItemResult]] = []
        for item in active:
            if item.memory_id in seen:
                continue
            score = len(transcript_tokens & _tokenize(" ".join([item.kind, item.key, item.summary])))
            if score:
                scored.append((score, item.observed_at, item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        for _, _, item in scored:
            add(item)

        if len(selected) < max(1, limit) and transcript.strip():
            for item in self.vector_search(person_id=person_id, text=transcript, limit=limit):
                add(item)

        return selected

    def _row_to_item(self, row: dict[str, Any]) -> MemoryItemResult:
        return MemoryItemResult(
            memory_id=str(row["memory_id"]),
            person_id=str(row.get("person_id") or ""),
            kind=str(row.get("kind") or ""),
            key=str(row.get("key") or ""),
            summary=str(row.get("summary") or ""),
            source=str(row.get("source") or ""),
            source_ref=str(row.get("source_ref") or ""),
            status=str(row.get("status") or "active"),
            observed_at=str(row.get("observed_at") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            due_at=str(row.get("due_at") or ""),
            expires_at=str(row.get("expires_at") or ""),
            metadata=_json_loads(row.get("metadata_json")),
            score=row.get("score") if isinstance(row.get("score"), float) else None,
        )


def _validate_update_fields(item: MemoryItemInput) -> None:
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
    normalized = "".join(char.casefold() if char.isalnum() else " " for char in str(text or ""))
    return {part for part in normalized.split() if len(part) >= 3}


class PersonMarkdownContextService:
    def __init__(self, runner: QueryRunner, embeddings: EmbeddingProvider | None = None) -> None:
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
        rows = self.runner.run(
            """
            MATCH (:Person {id: $person_id})-[:PARTICIPATED_IN]->(e:Episode)
            RETURN e.start_time AS start_time,
                   e.summary AS summary
            ORDER BY e.start_time DESC
            LIMIT $limit
            """,
            {"person_id": str(person_id or "").strip(), "limit": max(1, int(limit or 5))},
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


def _merge_items(left: list[MemoryItemResult], right: list[MemoryItemResult]) -> list[MemoryItemResult]:
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


def format_person_memory_markdown(
    items: list[MemoryItemResult],
    *,
    recent_episode_lines: list[str] | None = None,
    now: datetime | None = None,
    limit: int = 12,
) -> str:
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


def _section_lines(
    items: list[MemoryItemResult],
    kind: str,
    *,
    now: datetime | None,
    limit: int,
) -> list[str]:
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
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed is not None else 0.0


def _sanitize_context_line(value: str) -> str:
    rendered = " ".join(str(value or "").split())
    return rendered.lstrip("#-*[]>` ").strip()


def _operation_metadata(raw: dict[str, Any], *, default: dict[str, Any] | object) -> dict[str, Any] | object:
    if "metadata" not in raw:
        return default
    value = raw.get("metadata")
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("memory operation metadata must be an object")
    return dict(value)


def _extract_memory_for_participant(
    *,
    runner: QueryRunner,
    embeddings: EmbeddingProvider,
    extraction_provider: MemoryExtractionProvider,
    episode: EpisodeInput,
    participant: PersonInput,
    source_ref: str | None = None,
) -> PersonMemoryExtractionResult:
    memory_service = MemoryItemService(runner, embeddings)
    candidates = memory_service.candidate_items(
        person_id=participant.id,
        transcript=episode.transcript,
    )
    payload = extraction_provider.extract(
        person_id=participant.id,
        target_display_name=participant.display_name,
        transcript=episode.transcript,
        existing_memories=candidates,
        current_time=utc_now_iso(),
    )
    applied = _apply_memory_operations(
        memory_service,
        person_id=participant.id,
        operations=payload,
        source=participant.source,
        source_ref=source_ref or episode.id,
        observed_at=episode.end_time or episode.start_time,
        episode_id=episode.id,
        candidates=candidates,
    )
    return PersonMemoryExtractionResult(
        person_id=participant.id,
        update_requested=bool(isinstance(payload, dict) and payload.get("update")),
        created_memory_ids=applied["created"],
        updated_memory_ids=applied["updated"],
        archived_memory_ids=applied["archived"],
        skipped_ops=applied["skipped"],
    )


def _apply_memory_operations(
    memory_service: MemoryItemService,
    *,
    person_id: str,
    operations: dict[str, Any],
    source: str,
    source_ref: str,
    observed_at: str,
    episode_id: str,
    candidates: list[MemoryItemResult],
) -> dict[str, list[Any]]:
    applied: dict[str, list[Any]] = {"created": [], "updated": [], "archived": [], "skipped": []}
    if not isinstance(operations, dict) or not operations.get("update"):
        return applied
    candidate_by_id = {item.memory_id: item for item in candidates}
    for raw in operations.get("ops", []) or []:
        if not isinstance(raw, dict):
            applied["skipped"].append({"reason": "invalid_op", "op": raw})
            continue
        op = str(raw.get("op") or "").strip().casefold()
        if op == "noop":
            continue
        if op == "create":
            try:
                metadata = _operation_metadata(raw, default={})
                memory_id = memory_service.upsert_item(
                    person_id=person_id,
                    item=MemoryItemInput(
                        kind=str(raw.get("kind") or ""),
                        key=str(raw.get("key") or ""),
                        summary=str(raw.get("summary") or ""),
                        source=normalize_memory_source(source),
                        source_ref=source_ref,
                        observed_at=str(raw.get("observed_at") or observed_at),
                        due_at=str(raw.get("due_at") or ""),
                        expires_at=str(raw.get("expires_at") or ""),
                        metadata=metadata,
                    ),
                    supported_by_episode_id=episode_id,
                )
                applied["created"].append(memory_id)
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
                continue
            continue
        memory_id = str(raw.get("memory_id") or "").strip()
        if not memory_id or memory_id not in candidate_by_id:
            applied["skipped"].append({"reason": "unknown_memory_id", "op": raw})
            continue
        if op == "archive":
            if memory_service.archive_item(memory_id):
                applied["archived"].append(memory_id)
            else:
                applied["skipped"].append({"reason": "archive_noop", "op": raw})
        elif op == "update":
            raw_due_at = str(raw.get("due_at") or "").strip()
            raw_expires_at = str(raw.get("expires_at") or "").strip()
            due_at = raw_due_at if raw_due_at else _PRESERVE
            expires_at = raw_expires_at if raw_expires_at else _PRESERVE
            try:
                metadata = _operation_metadata(raw, default=_PRESERVE)
                updated = memory_service.update_item(
                    memory_id,
                    summary=str(raw.get("summary") or ""),
                    source_ref=source_ref,
                    observed_at=str(raw.get("observed_at") or observed_at),
                    due_at=due_at,
                    expires_at=expires_at,
                    metadata=metadata,
                    supported_by_episode_id=episode_id,
                )
                if updated:
                    applied["updated"].append(memory_id)
                else:
                    applied["skipped"].append({"reason": "update_noop", "op": raw})
            except ValueError as exc:
                applied["skipped"].append({"reason": str(exc), "op": raw})
                continue
        else:
            applied["skipped"].append({"reason": "unknown_operation", "op": raw})
    return applied


class EpisodeMemoryExtractionService:
    def __init__(
        self,
        runner: QueryRunner,
        embeddings: EmbeddingProvider,
        extraction_provider: MemoryExtractionProvider,
    ) -> None:
        self.runner = runner
        self.embeddings = embeddings
        self.extraction_provider = extraction_provider

    def extract_for_episode(
        self,
        episode: EpisodeInput,
        *,
        person_id: str | None = None,
        speaker_only: bool = False,
    ) -> EpisodeMemoryExtractionResult:
        participants = self._target_participants(episode, person_id=person_id, speaker_only=speaker_only)
        results: list[PersonMemoryExtractionResult] = []
        errors: list[dict[str, str]] = []
        for participant in participants:
            try:
                result = _extract_memory_for_participant(
                    runner=self.runner,
                    embeddings=self.embeddings,
                    extraction_provider=self.extraction_provider,
                    episode=episode,
                    participant=participant,
                )
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                result = PersonMemoryExtractionResult(person_id=participant.id, error=error)
                errors.append({"person_id": participant.id, "error": error})
            results.append(result)
        return EpisodeMemoryExtractionResult(
            episode_id=episode.id,
            memory_results=results,
            memory_errors=errors,
        )

    def extract_for_stored_episode(
        self,
        episode_id: str,
        *,
        person_id: str | None = None,
        speaker_only: bool = True,
    ) -> EpisodeMemoryExtractionResult:
        episode = self.load_episode(episode_id)
        return self.extract_for_episode(episode, person_id=person_id, speaker_only=speaker_only if person_id is None else False)

    def load_episode(self, episode_id: str) -> EpisodeInput:
        rendered = str(episode_id or "").strip()
        if not rendered:
            raise ValueError("episode_id is required")
        rows = self.runner.run(
            """
            MATCH (e:Episode {id: $episode_id})
            OPTIONAL MATCH (e)-[:OCCURRED_AT]->(place:Place)
            RETURN e.id AS id,
                   e.episode_type AS episode_type,
                   e.start_time AS start_time,
                   e.end_time AS end_time,
                   e.summary AS summary,
                   e.transcript AS transcript,
                   e.retention_class AS retention_class,
                   place.building_code AS building_code,
                   place.room_id AS room_id
            """,
            {"episode_id": rendered},
        )
        if not rows:
            raise ValueError(f"episode not found: {rendered}")
        row = rows[0]
        participants = self._load_participants(rendered)
        return EpisodeInput(
            id=str(row.get("id") or rendered),
            episode_type=str(row.get("episode_type") or "conversation"),
            start_time=str(row.get("start_time") or ""),
            end_time=str(row.get("end_time") or "") or None,
            summary=str(row.get("summary") or ""),
            transcript=str(row.get("transcript") or ""),
            retention_class=str(row.get("retention_class") or "standard"),
            place=PlaceInput(
                building_code=str(row.get("building_code") or "UNKNOWN"),
                room_id=str(row.get("room_id") or "UNKNOWN"),
            ),
            participants=participants,
        )

    def _load_participants(self, episode_id: str) -> list[PersonInput]:
        rows = self.runner.run(
            """
            MATCH (p:Person)-[r:PARTICIPATED_IN]->(:Episode {id: $episode_id})
            RETURN p.id AS id,
                   p.display_name AS display_name,
                   p.email AS email,
                   p.consent_status AS consent_status,
                   r.role AS role,
                   r.source AS source
            ORDER BY p.id
            """,
            {"episode_id": episode_id},
        )
        return [
            PersonInput(
                id=str(row.get("id") or ""),
                display_name=row.get("display_name"),
                email=row.get("email"),
                consent_status=row.get("consent_status"),
                role=str(row.get("role") or "participant"),
                source=str(row.get("source") or "caller"),
            )
            for row in rows
            if str(row.get("id") or "").strip()
        ]

    def _target_participants(
        self,
        episode: EpisodeInput,
        *,
        person_id: str | None,
        speaker_only: bool,
    ) -> list[PersonInput]:
        if person_id is not None:
            rendered = str(person_id or "").strip()
            matches = [participant for participant in episode.participants if participant.id == rendered]
            if not matches:
                raise ValueError(f"person {rendered!r} is not linked to episode {episode.id!r}")
            return matches
        if not speaker_only:
            return list(episode.participants)
        speakers = [participant for participant in episode.participants if participant.role == "speaker"]
        return speakers or list(episode.participants)


class OpenAIMemoryExtractionProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-5.5",
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    def extract(
        self,
        *,
        person_id: str,
        target_display_name: str | None = None,
        transcript: str,
        existing_memories: list[MemoryItemResult],
        current_time: str,
    ) -> dict[str, Any]:
        response = self._openai_client().responses.create(
            model=self.model,
            text=MEMORY_EXTRACTION_TEXT_FORMAT,
            input=[
                {
                    "role": "developer",
                    "content": (
                        "Extract durable person memory from a transcript for a workplace social agent. "
                        "Extract only for the target person. In multi-speaker transcripts, only create memory "
                        "that is explicitly stated by the target person or explicitly about the target person. "
                        "Allowed kinds are preference, boundary, pet, fact, and followup. "
                        "Facts must be narrow person-prompt context, not ontology triples, inferred traits, "
                        "directory attributes, or general world knowledge. "
                        "Do not create notes. Do not store org chart, title, manager, team, cost center, "
                        "or inferred personality. Followups must include expires_at and should include due_at. "
                        "Return JSON only with update and ops. Ops may be create, update, archive, or noop. "
                        "Prefer updating existing memories over creating duplicates."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_time": current_time,
                            "person_id": person_id,
                            "target_display_name": target_display_name,
                            "existing_memories": [self._memory_payload(item) for item in existing_memories],
                            "transcript": transcript,
                        },
                        sort_keys=True,
                    ),
                },
            ],
        )
        text = self._extract_text(response)
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError("OpenAI memory extraction did not return valid JSON") from exc
        return payload if isinstance(payload, dict) else {"update": False, "ops": []}

    def _memory_payload(self, item: MemoryItemResult) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "memory_id": item.memory_id,
            "kind": item.kind,
            "key": item.key,
            "summary": item.summary,
        }
        if item.due_at:
            payload["due_at"] = item.due_at
        if item.expires_at:
            payload["expires_at"] = item.expires_at
        return payload

    def _openai_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for OpenAI memory extraction.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIConfigurationError("Install the openai package to use OpenAI memory extraction.") from exc
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _extract_text(self, response: Any) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if output_text:
                return str(output_text).strip()
            return str(response["output"][0]["content"][0]["text"]).strip()
        if getattr(response, "output_text", None):
            return str(response.output_text).strip()
        return str(response.output[0].content[0].text).strip()


class _NoopEmbeddingProvider(EmbeddingProvider):
    def embed(self, text: str) -> list[float]:
        del text
        raise ValueError("An embedding provider is required for vector memory item search.")
