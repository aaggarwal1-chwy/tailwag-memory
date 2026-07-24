from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
from typing import Any, Literal

JobType = Literal[
    "slack_poll",
    "memory_extract_episode",
    "memory_consolidate_person",
    "memory_consolidate_all",
    "relay_maintenance",
    "report_generate",
]


class JobPayloadError(ValueError):
    """Raised when an AWS worker job payload is invalid."""


@dataclass(frozen=True)
class SlackPollJob:
    """Describe one Slack channel polling job."""

    job_id: str
    channel: str
    job_type: Literal["slack_poll"] = "slack_poll"
    backfill_hours: float | None = None
    force_backfill: bool = False
    history_limit: int = 200
    reply_limit: int = 200
    extract_memory: bool = False
    enqueue_memory_extraction: bool = True
    include_email: bool = True
    retention_class: str = "standard"
    active_thread_hours: float = 24.0


@dataclass(frozen=True)
class MemoryExtractEpisodeJob:
    """Describe durable memory extraction for one stored episode."""

    job_id: str
    episode_id: str
    job_type: Literal["memory_extract_episode"] = "memory_extract_episode"
    person_id: str | None = None


@dataclass(frozen=True)
class MemoryConsolidatePersonJob:
    """Describe memory consolidation for one person."""

    job_id: str
    person_id: str
    job_type: Literal["memory_consolidate_person"] = "memory_consolidate_person"
    min_evidence_episodes: int | None = None
    seed_limit: int | None = None
    neighbor_limit: int | None = None
    cluster_limit: int | None = None
    episode_text_limit: int | None = None


@dataclass(frozen=True)
class MemoryConsolidateAllJob:
    """Describe memory consolidation for a bounded set of people."""

    job_id: str
    job_type: Literal["memory_consolidate_all"] = "memory_consolidate_all"
    person_limit: int = 100
    min_evidence_episodes: int | None = None
    seed_limit: int | None = None
    neighbor_limit: int | None = None
    cluster_limit: int | None = None
    episode_text_limit: int | None = None


@dataclass(frozen=True)
class RelayMaintenanceJob:
    """Expire stale relay messages and release abandoned claims."""

    job_id: str
    job_type: Literal["relay_maintenance"] = "relay_maintenance"
    now: str = ""
    claim_timeout_seconds: int = 120


@dataclass(frozen=True)
class ReportGenerateJob:
    """Describe static report generation and publishing."""

    job_id: str
    reports: list[str] = field(default_factory=lambda: ["memory_items", "person_timeline", "followup_validity"])
    job_type: Literal["report_generate"] = "report_generate"
    output_prefix: str = "reports/"
    person_id: str | None = None
    limit: int = 1000
    include_assets: bool = True


WorkerJob = (
    SlackPollJob
    | MemoryExtractEpisodeJob
    | MemoryConsolidatePersonJob
    | MemoryConsolidateAllJob
    | RelayMaintenanceJob
    | ReportGenerateJob
)


def parse_job_payload(payload: str | bytes | dict[str, Any]) -> WorkerJob:
    """Parse and validate one worker job payload."""
    raw = _payload_dict(payload)
    job_type = _required_str(raw, "job_type")
    job_id = _required_str(raw, "job_id")

    if job_type == "slack_poll":
        return SlackPollJob(
            job_id=job_id,
            channel=_required_str(raw, "channel"),
            backfill_hours=_optional_float(raw.get("backfill_hours"), "backfill_hours"),
            force_backfill=_bool(raw.get("force_backfill"), default=False),
            history_limit=_positive_int(raw.get("history_limit"), "history_limit", default=200),
            reply_limit=_positive_int(raw.get("reply_limit"), "reply_limit", default=200),
            extract_memory=_bool(raw.get("extract_memory"), default=False),
            enqueue_memory_extraction=_bool(raw.get("enqueue_memory_extraction"), default=True),
            include_email=_bool(raw.get("include_email"), default=True),
            retention_class=_optional_str(raw.get("retention_class"), default="standard"),
            active_thread_hours=_positive_float(raw.get("active_thread_hours"), "active_thread_hours", default=24.0),
        )
    if job_type == "memory_extract_episode":
        return MemoryExtractEpisodeJob(
            job_id=job_id,
            episode_id=_required_str(raw, "episode_id"),
            person_id=_optional_str(raw.get("person_id"), default=None),
        )
    if job_type == "memory_consolidate_person":
        return MemoryConsolidatePersonJob(
            job_id=job_id,
            person_id=_required_str(raw, "person_id"),
            min_evidence_episodes=_optional_positive_int(raw.get("min_evidence_episodes"), "min_evidence_episodes"),
            seed_limit=_optional_positive_int(raw.get("seed_limit"), "seed_limit"),
            neighbor_limit=_optional_positive_int(raw.get("neighbor_limit"), "neighbor_limit"),
            cluster_limit=_optional_positive_int(raw.get("cluster_limit"), "cluster_limit"),
            episode_text_limit=_optional_positive_int(raw.get("episode_text_limit"), "episode_text_limit"),
        )
    if job_type == "memory_consolidate_all":
        return MemoryConsolidateAllJob(
            job_id=job_id,
            person_limit=_positive_int(raw.get("person_limit"), "person_limit", default=100),
            min_evidence_episodes=_optional_positive_int(raw.get("min_evidence_episodes"), "min_evidence_episodes"),
            seed_limit=_optional_positive_int(raw.get("seed_limit"), "seed_limit"),
            neighbor_limit=_optional_positive_int(raw.get("neighbor_limit"), "neighbor_limit"),
            cluster_limit=_optional_positive_int(raw.get("cluster_limit"), "cluster_limit"),
            episode_text_limit=_optional_positive_int(raw.get("episode_text_limit"), "episode_text_limit"),
        )
    if job_type == "relay_maintenance":
        return RelayMaintenanceJob(
            job_id=job_id,
            now=_optional_str(raw.get("now"), default="") or "",
            claim_timeout_seconds=_positive_int(
                raw.get("claim_timeout_seconds"),
                "claim_timeout_seconds",
                default=120,
            ),
        )
    if job_type == "report_generate":
        reports = raw.get("reports", ["memory_items", "person_timeline", "followup_validity"])
        if not isinstance(reports, list) or not all(isinstance(report, str) and report.strip() for report in reports):
            raise JobPayloadError("reports must be a list of non-empty strings")
        return ReportGenerateJob(
            job_id=job_id,
            reports=[report.strip() for report in reports],
            output_prefix=_optional_str(raw.get("output_prefix"), default="reports/") or "",
            person_id=_optional_str(raw.get("person_id"), default=None),
            limit=_positive_int(raw.get("limit"), "limit", default=1000),
            include_assets=_bool(raw.get("include_assets"), default=True),
        )
    raise JobPayloadError(f"unknown job_type: {job_type!r}")


def job_to_dict(job: WorkerJob) -> dict[str, Any]:
    """Return a JSON-compatible payload for one worker job."""
    if not is_dataclass(job):
        raise TypeError("job must be a worker job dataclass")
    return asdict(job)


def job_to_json(job: WorkerJob) -> str:
    """Serialize one worker job as stable JSON."""
    return json.dumps(job_to_dict(job), sort_keys=True, separators=(",", ":"))


def parse_sqs_event(event: dict[str, Any]) -> list[tuple[str, WorkerJob]]:
    """Parse an AWS SQS Lambda event into message ids and jobs."""
    records = event.get("Records", [])
    if not isinstance(records, list):
        raise JobPayloadError("SQS event Records must be a list")
    parsed: list[tuple[str, WorkerJob]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise JobPayloadError(f"SQS record {index} must be an object")
        message_id = str(record.get("messageId") or record.get("messageID") or index)
        parsed.append((message_id, parse_job_payload(record.get("body", ""))))
    return parsed


def _payload_dict(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if not isinstance(payload, str) or not payload.strip():
        raise JobPayloadError("job payload must be a non-empty JSON object")
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise JobPayloadError("job payload must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise JobPayloadError("job payload must be a JSON object")
    return raw


def _required_str(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise JobPayloadError(f"{name} is required")
    return value.strip()


def _optional_str(value: object, *, default: str | None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise JobPayloadError("optional string values must be strings")
    rendered = value.strip()
    return rendered or default


def _bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise JobPayloadError("boolean fields must be true or false")


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _positive_float(value, name, default=None)


def _positive_float(value: object, name: str, *, default: float | None) -> float:
    if value is None:
        if default is None:
            raise JobPayloadError(f"{name} is required")
        return default
    try:
        rendered = float(value)
    except (TypeError, ValueError) as exc:
        raise JobPayloadError(f"{name} must be a positive number") from exc
    if rendered <= 0:
        raise JobPayloadError(f"{name} must be a positive number")
    return rendered


def _positive_int(value: object, name: str, *, default: int) -> int:
    if value is None:
        return default
    rendered = _optional_positive_int(value, name)
    if rendered is None:
        return default
    return rendered


def _optional_positive_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise JobPayloadError(f"{name} must be a positive integer")
    try:
        rendered = int(value)
    except (TypeError, ValueError) as exc:
        raise JobPayloadError(f"{name} must be a positive integer") from exc
    if rendered <= 0:
        raise JobPayloadError(f"{name} must be a positive integer")
    return rendered
