from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from typing import Any

from ..db import QueryRunner
from ..models import utc_now_iso
from .models import InspectMemoryAddressedEpisode, InspectMemoryItem, InspectSankeyLink
from .reports import InspectReport

_TERMINAL_ORDER = ["still_active", "addressed", "superseded", "expired_active", "invalid", "other"]
_TERMINAL_LABELS = {
    "still_active": "Still Active",
    "addressed": "Addressed",
    "superseded": "Superseded",
    "expired_active": "Expired Active",
    "invalid": "Invalid",
    "other": "Other Inactive",
}


class MemoryItemInspectService:
    """Fetch memory item rows for local read-only inspection reports."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store the Neo4j query runner."""

        self.runner = runner

    def items(
        self,
        *,
        person_id: str | None = None,
        limit: int = 1000,
        now: datetime | None = None,
    ) -> list[InspectMemoryItem]:
        """Return memory items with evidence and lifecycle relationship state."""

        bounded_limit = _bounded_positive_limit(limit, default=1000)
        if bounded_limit == 0:
            return []
        rendered_person_id = str(person_id or "").strip()
        rows = self.runner.run(
            """
            MATCH (person:Person)-[:HAS_MEMORY]->(memory:MemoryItem)
            WHERE ($person_id = '' OR person.id = $person_id)
            OPTIONAL MATCH (memory)-[:SUPPORTED_BY]->(support:Episode)
            WITH person, memory, collect(DISTINCT support.id) AS supported_episode_ids
            OPTIONAL MATCH (memory)-[addressed:ADDRESSED_BY]->(addressed_episode:Episode)
            WITH person, memory, supported_episode_ids,
                 collect(DISTINCT {
                   episode_id: addressed_episode.id,
                   addressed_at: addressed.addressed_at
                 }) AS addressed_by
            OPTIONAL MATCH (memory)-[:SUPERSEDED_BY]->(replacement:MemoryItem)
            WITH person, memory, supported_episode_ids, addressed_by,
                 collect(DISTINCT replacement.id) AS superseded_by_memory_ids
            OPTIONAL MATCH (source:MemoryItem)-[:SUPERSEDED_BY]->(memory)
            RETURN person.id AS person_id,
                   person.display_name AS display_name,
                   memory.id AS memory_id,
                   memory.kind AS kind,
                   memory.key AS key,
                   memory.summary AS summary,
                   memory.source AS source,
                   memory.source_ref AS source_ref,
                   coalesce(memory.status, 'active') AS status,
                   memory.observed_at AS observed_at,
                   memory.created_at AS created_at,
                   memory.updated_at AS updated_at,
                   memory.due_at AS due_at,
                   memory.expires_at AS expires_at,
                   memory.metadata_json AS metadata_json,
                   supported_episode_ids AS supported_episode_ids,
                   addressed_by AS addressed_by,
                   superseded_by_memory_ids AS superseded_by_memory_ids,
                   collect(DISTINCT source.id) AS supersedes_memory_ids
            ORDER BY person.id ASC, memory.kind ASC, memory.observed_at DESC, memory.updated_at DESC, memory.id ASC
            LIMIT $limit
            """,
            {"person_id": rendered_person_id, "limit": bounded_limit},
        )
        reference_time = now or datetime.now(timezone.utc)
        return [_row_to_item(row, now=reference_time) for row in rows]

    def episode_conversion(self) -> dict[str, int]:
        """Return episode counts for the memory overview Sankey."""

        rows = self.runner.run(
            """
            MATCH (episode:Episode)
            OPTIONAL MATCH (episode)<-[:SUPPORTED_BY]-(memory:MemoryItem)<-[:HAS_MEMORY]-(:Person)
            RETURN count(DISTINCT episode) AS episode_count,
                   count(DISTINCT CASE WHEN memory IS NULL THEN null ELSE episode END) AS memory_episode_count,
                   count(DISTINCT memory) AS memory_count
            """,
            {},
        )
        row = rows[0] if rows else {}
        episode_count = _int(row.get("episode_count"))
        memory_episode_count = _int(row.get("memory_episode_count"))
        memory_count = _int(row.get("memory_count"))
        return {
            "episode_count": episode_count,
            "memory_episode_count": memory_episode_count,
            "memory_count": memory_count,
        }


def memory_items_report(
    items: list[InspectMemoryItem],
    *,
    person_id: str | None = None,
    limit: int = 1000,
    episode_conversion: dict[str, int] | None = None,
    generated_at: str | None = None,
) -> InspectReport:
    """Build a report envelope for memory item inspection exports."""

    filters = {"person_id": person_id, "limit": limit}
    records = [asdict(item) for item in items]
    overview_links = _overview_links(records, episode_conversion or {})
    return InspectReport(
        title="Memory Items",
        generated_at=generated_at or utc_now_iso(),
        filters=filters,
        records=records,
        metadata={
            "utility": "inspect memory-items",
            "storage": "read_only",
            "canonical_reports": {
                "memory_items": "tailwag-memory-items.html",
                "person_timeline": "tailwag-person-timeline.html",
                "affect": "tailwag-affect.html",
            },
            "distributions": _distributions(records),
            "overview_links": [asdict(link) for link in overview_links],
            "episode_counts": _episode_counts(overview_links),
            "terminal_counts": _terminal_counts(overview_links),
        },
        warnings=[] if items else ["No memory items matched the selected filters."],
    )


def _overview_links(records: list[dict[str, object]], episode_conversion: dict[str, int]) -> list[InspectSankeyLink]:
    """Build the memory-items overview Sankey links."""

    links = _episode_links(episode_conversion)
    terminal_counts = {key: 0 for key in _TERMINAL_ORDER}
    for record in records:
        terminal_counts[_terminal_state(record)] += 1
    total = sum(terminal_counts.values())
    if total:
        links.append(InspectSankeyLink(source="Created", target="Active", count=total))
    links.extend(
        InspectSankeyLink(source="Active", target=_TERMINAL_LABELS[key], count=count)
        for key, count in terminal_counts.items()
        if count > 0
    )
    return links


def _episode_links(episode_conversion: dict[str, int]) -> list[InspectSankeyLink]:
    """Build episode-to-memory Sankey links."""

    episode_count = _int(episode_conversion.get("episode_count"))
    memory_episode_count = _int(episode_conversion.get("memory_episode_count"))
    memory_count = _int(episode_conversion.get("memory_count"))
    without_memory_count = max(0, episode_count - memory_episode_count)
    links: list[InspectSankeyLink] = []
    if memory_episode_count:
        links.append(InspectSankeyLink("All Episodes", "Episodes With Memories", memory_episode_count))
    if without_memory_count:
        links.append(InspectSankeyLink("All Episodes", "Episodes Without Memories", without_memory_count))
    if memory_count:
        links.append(InspectSankeyLink("Episodes With Memories", "Created", memory_count))
    return links


def _terminal_counts(links: list[InspectSankeyLink]) -> dict[str, int]:
    """Return terminal lifecycle counts from overview links."""

    return {link.target: link.count for link in links if link.source == "Active"}


def _episode_counts(links: list[InspectSankeyLink]) -> dict[str, int]:
    """Return episode conversion counts from overview links."""

    with_memory = _link_count(links, "All Episodes", "Episodes With Memories")
    without_memory = _link_count(links, "All Episodes", "Episodes Without Memories")
    memory_count = _link_count(links, "Episodes With Memories", "Created")
    counts: dict[str, int] = {}
    if with_memory or without_memory:
        counts["All Episodes"] = with_memory + without_memory
        counts["Episodes With Memories"] = with_memory
        counts["Episodes Without Memories"] = without_memory
    if memory_count:
        counts["Memory Items From Episodes"] = memory_count
    return counts


def _link_count(links: list[InspectSankeyLink], source: str, target: str) -> int:
    """Return the count for one Sankey link."""

    for link in links:
        if link.source == source and link.target == target:
            return link.count
    return 0


def _terminal_state(record: dict[str, object]) -> str:
    """Return the lifecycle terminal state for one memory item record."""

    status = _string(record.get("status")) or "active"
    kind = _string(record.get("kind"))
    if status == "superseded" or _has_values(record.get("superseded_by_memory_ids")):
        return "superseded"
    if status == "addressed" or _has_values(record.get("addressed_by")):
        return "addressed"
    if kind == "followup":
        followup_state = _string(record.get("followup_state"))
        if followup_state in {"expired_active", "invalid"}:
            return followup_state
    if status == "active":
        return "still_active"
    return "other"


def _row_to_item(row: dict[str, object], *, now: datetime) -> InspectMemoryItem:
    """Convert one Neo4j memory row into an inspection item."""

    kind = _string(row.get("kind"))
    status = _string(row.get("status")) or "active"
    addressed_by = _addressed_by(row.get("addressed_by"))
    superseded_by_memory_ids = _string_list(row.get("superseded_by_memory_ids"))
    item = InspectMemoryItem(
        memory_id=_string(row.get("memory_id")),
        person_id=_string(row.get("person_id")),
        display_name=_optional_string(row.get("display_name")),
        kind=kind,
        key=_string(row.get("key")),
        summary=_string(row.get("summary")),
        source=_string(row.get("source")),
        source_ref=_string(row.get("source_ref")),
        status=status,
        observed_at=_string(row.get("observed_at")),
        created_at=_string(row.get("created_at")),
        updated_at=_string(row.get("updated_at")),
        due_at=_string(row.get("due_at")),
        expires_at=_string(row.get("expires_at")),
        metadata=_metadata(row.get("metadata_json")),
        supported_episode_ids=_string_list(row.get("supported_episode_ids")),
        addressed_by=addressed_by,
        superseded_by_memory_ids=superseded_by_memory_ids,
        supersedes_memory_ids=_string_list(row.get("supersedes_memory_ids")),
    )
    return InspectMemoryItem(
        **{
            **asdict(item),
            "addressed_by": addressed_by,
            "followup_state": _followup_state(item, now=now),
        }
    )


def _followup_state(item: InspectMemoryItem, *, now: datetime) -> str:
    """Return the follow-up board state for one memory item."""

    if item.status == "superseded" or item.superseded_by_memory_ids:
        return "superseded"
    if item.kind != "followup":
        return "not_followup"
    if item.status == "addressed" or item.addressed_by:
        return "addressed"
    if item.status != "active":
        return item.status or "inactive"

    due_at = _parse_time(item.due_at)
    expires_at = _parse_time(item.expires_at)
    if not item.expires_at or expires_at is None:
        return "invalid"
    if item.due_at and due_at is None:
        return "invalid"
    if due_at is not None and expires_at < due_at:
        return "invalid"
    if expires_at is not None and now > expires_at:
        return "expired_active"
    if due_at is not None and now < due_at:
        return "not_yet_due"
    return "visible_now"


def _distributions(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    """Return report distribution counts for memory item records."""

    distributions: dict[str, dict[str, int]] = {
        "kind": {},
        "status": {},
        "source": {},
        "person": {},
        "followup_state": {},
    }
    for record in records:
        _increment(distributions["kind"], record.get("kind") or "unknown")
        _increment(distributions["status"], _display_status(record))
        _increment(distributions["source"], record.get("source") or "unknown")
        _increment(distributions["person"], record.get("person_id") or "unknown")
        _increment(distributions["followup_state"], record.get("followup_state") or "unknown")
    return distributions


def _display_status(record: dict[str, object]) -> object:
    """Return the status bucket used by memory inspection reports."""

    if record.get("status") == "superseded" or _has_values(record.get("superseded_by_memory_ids")):
        return "superseded"
    return record.get("status") or "unknown"


def _has_values(raw: object) -> bool:
    """Return whether a collected row value has any truthy entries."""

    return isinstance(raw, list) and any(str(value or "").strip() for value in raw)


def _increment(bucket: dict[str, int], value: object) -> None:
    """Increment a string-keyed distribution bucket."""

    key = str(value or "unknown")
    bucket[key] = bucket.get(key, 0) + 1


def _bounded_positive_limit(limit: int, *, default: int) -> int:
    """Return a non-negative limit with a caller-provided default."""

    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return default


def _metadata(raw: object) -> dict[str, Any]:
    """Decode a stored memory metadata JSON payload."""

    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {"_unparseable_metadata_json": raw}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _addressed_by(raw: object) -> list[InspectMemoryAddressedEpisode]:
    """Return addressed episode records from a collected Cypher value."""

    if not isinstance(raw, list):
        return []
    addressed: list[InspectMemoryAddressedEpisode] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            continue
        episode_id = _string(value.get("episode_id"))
        if not episode_id or episode_id in seen:
            continue
        seen.add(episode_id)
        addressed.append(
            InspectMemoryAddressedEpisode(
                episode_id=episode_id,
                addressed_at=_string(value.get("addressed_at")),
            )
        )
    return addressed


def _string_list(raw: object) -> list[str]:
    """Return distinct non-empty strings while preserving input order."""

    if not isinstance(raw, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for value in raw:
        rendered = _string(value)
        if rendered and rendered not in seen:
            seen.add(rendered)
            values.append(rendered)
    return values


def _optional_string(value: object) -> str | None:
    """Return a stripped string or None."""

    rendered = _string(value)
    return rendered or None


def _int(value: object) -> int:
    """Return a non-negative integer count from a Neo4j row value."""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _string(value: object) -> str:
    """Return a stripped string for optional row values."""

    if value is None:
        return ""
    return str(value).strip()


def _parse_time(value: str) -> datetime | None:
    """Parse an ISO timestamp into an aware datetime when possible."""

    rendered = str(value or "").strip()
    if not rendered:
        return None
    try:
        parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
