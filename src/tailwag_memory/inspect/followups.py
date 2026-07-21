from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from ..db import QueryRunner
from ..models import utc_now_iso
from .models import InspectFollowupValidityItem, InspectReport

_BUCKET_ORDER = [
    "invalid",
    "under_1_day",
    "1_to_3_days",
    "4_to_7_days",
    "8_to_14_days",
    "15_to_30_days",
    "over_30_days",
]


class FollowupValidityInspectService:
    """Fetch follow-up memory items grouped by validity-window duration."""

    def __init__(self, runner: QueryRunner) -> None:
        """Store the Neo4j query runner."""

        self.runner = runner

    def items(
        self,
        *,
        limit: int = 1000,
        now: datetime | None = None,
    ) -> list[InspectFollowupValidityItem]:
        """Return follow-up items with computed state and validity bucket."""

        bounded_limit = _bounded_positive_limit(limit, default=1000)
        if bounded_limit == 0:
            return []
        rows = self.runner.run(
            """
            MATCH (person:Person)-[:HAS_MEMORY]->(memory:MemoryItem)
            WHERE memory.kind = 'followup'
            OPTIONAL MATCH (memory)-[addressed:ADDRESSED_BY]->(addressed_episode:Episode)
            OPTIONAL MATCH (memory)-[:SUPERSEDED_BY]->(replacement:MemoryItem)
            RETURN person.id AS person_id,
                   person.display_name AS display_name,
                   memory.id AS memory_id,
                   memory.summary AS summary,
                   coalesce(memory.status, 'active') AS status,
                   memory.observed_at AS observed_at,
                   memory.created_at AS created_at,
                   memory.updated_at AS updated_at,
                   memory.due_at AS due_at,
                   memory.expires_at AS expires_at,
                   count(DISTINCT addressed_episode) AS addressed_count,
                   count(DISTINCT replacement) AS superseded_count
            ORDER BY memory.expires_at ASC, memory.due_at ASC, person.id ASC, memory.id ASC
            LIMIT $limit
            """,
            {"limit": bounded_limit},
        )
        reference_time = now or datetime.now(timezone.utc)
        return [_row_to_item(row, now=reference_time) for row in rows]


def followup_validity_report(
    items: list[InspectFollowupValidityItem],
    *,
    limit: int = 1000,
    generated_at: str | None = None,
) -> InspectReport:
    """Build a report envelope for follow-up validity duration inspection."""

    records = [asdict(item) for item in items]
    return InspectReport(
        title="Follow-Up Validity",
        generated_at=generated_at or utc_now_iso(),
        filters={"limit": limit},
        records=records,
        metadata={
            "utility": "inspect followup-validity",
            "storage": "read_only",
            "bucket_order": _BUCKET_ORDER,
            "distributions": {
                "validity_bucket": _distribution(records, "validity_bucket"),
                "followup_state": _distribution(records, "followup_state"),
            },
            "canonical_reports": {
                "followup_validity": "tailwag-followup-validity.html",
                "memory_items": "tailwag-memory-items.html",
                "person_timeline": "tailwag-person-timeline.html",
                "affect": "tailwag-affect.html",
            },
        },
        warnings=[] if items else ["No follow-up memory items matched this export."],
    )


def _row_to_item(row: dict[str, object], *, now: datetime) -> InspectFollowupValidityItem:
    """Convert one Neo4j row into a validity inspection item."""

    due_at = _string(row.get("due_at"))
    expires_at = _string(row.get("expires_at"))
    validity_start = due_at or _string(row.get("observed_at")) or _string(row.get("created_at")) or _string(row.get("updated_at"))
    validity_seconds = _validity_seconds(validity_start, expires_at)
    return InspectFollowupValidityItem(
        memory_id=_string(row.get("memory_id")),
        person_id=_string(row.get("person_id")),
        display_name=_optional_string(row.get("display_name")),
        summary=_string(row.get("summary")),
        status=_string(row.get("status")) or "active",
        followup_state=_followup_state(row, due_at=due_at, expires_at=expires_at, now=now),
        due_at=due_at,
        expires_at=expires_at,
        validity_seconds=validity_seconds,
        validity_bucket=_validity_bucket(validity_seconds),
    )


def _followup_state(row: dict[str, object], *, due_at: str, expires_at: str, now: datetime) -> str:
    """Return the follow-up state relevant to the validity-duration report."""

    status = _string(row.get("status")) or "active"
    if _int(row.get("superseded_count")) > 0 or status == "superseded":
        return "superseded"
    if _int(row.get("addressed_count")) > 0 or status == "addressed":
        return "addressed"
    if status != "active":
        return status

    due = _parse_time(due_at)
    expires = _parse_time(expires_at)
    if not expires_at or expires is None:
        return "invalid"
    if due_at and due is None:
        return "invalid"
    if due is not None and expires < due:
        return "invalid"
    if now > expires:
        return "expired_active"
    if due is not None and now < due:
        return "not_yet_due"
    return "visible_now"


def _validity_seconds(starts_at: str, expires_at: str) -> int | None:
    """Return the validity window in seconds, or None when invalid."""

    expires = _parse_time(expires_at)
    if expires is None:
        return None
    start = _parse_time(starts_at) if starts_at else None
    if start is None:
        return None
    seconds = int((expires - start).total_seconds())
    return seconds if seconds >= 0 else None


def _validity_bucket(seconds: int | None) -> str:
    """Return the duration bucket for a follow-up validity window."""

    if seconds is None:
        return "invalid"
    days = seconds / 86400
    if days < 1:
        return "under_1_day"
    if days <= 3:
        return "1_to_3_days"
    if days <= 7:
        return "4_to_7_days"
    if days <= 14:
        return "8_to_14_days"
    if days <= 30:
        return "15_to_30_days"
    return "over_30_days"


def _distribution(records: list[dict[str, object]], key: str) -> dict[str, int]:
    """Return a string distribution for one record key."""

    distribution: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unknown")
        distribution[value] = distribution.get(value, 0) + 1
    return distribution


def _bounded_positive_limit(limit: int, *, default: int) -> int:
    """Return a non-negative limit with a caller-provided default."""

    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return default


def _parse_time(value: str) -> datetime | None:
    """Parse an ISO timestamp string."""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _int(value: object) -> int:
    """Return a non-negative integer count from a Neo4j row value."""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_string(value: object) -> str | None:
    """Return a stripped string or None."""

    rendered = _string(value)
    return rendered or None


def _string(value: object) -> str:
    """Return a stripped string."""

    return str(value or "").strip()
