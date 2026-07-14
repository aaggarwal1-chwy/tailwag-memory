from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tailwag_memory.inspect.followup_report import followup_validity_report_html
from tailwag_memory.inspect.followups import FollowupValidityInspectService, followup_validity_report
from tailwag_memory.inspect.html_utils import INSPECT_CSS_FILENAME, INSPECT_JS_FILENAME, inspect_asset_text
from tailwag_memory.inspect.memory_items import MemoryItemInspectService, memory_items_report
from tailwag_memory.inspect.memory_report import memory_items_report_html
from tailwag_memory.inspect.reports import InspectReport
from tailwag_memory.inspect.timeline import PersonTimelineRetrievalService
from tailwag_memory.inspect.timeline_report import person_timeline_report_html
from tailwag_memory.inspect.reports import person_timeline_report


@dataclass(frozen=True)
class PublishedReport:
    """One report object written to S3."""

    key: str
    content_type: str


def render_report_files(
    runner: Any,
    *,
    reports: list[str],
    person_id: str | None = None,
    limit: int = 1000,
    include_assets: bool = True,
) -> dict[str, tuple[str, str]]:
    """Render selected Tailwag inspect reports as S3 object name to content."""
    rendered: dict[str, tuple[str, str]] = {}
    for report in reports:
        if report == "followup_validity":
            items = FollowupValidityInspectService(runner).items(limit=limit)
            envelope = followup_validity_report(items, limit=limit)
            rendered["tailwag-followup-validity.html"] = (followup_validity_report_html(envelope), "text/html; charset=utf-8")
        elif report == "memory_items":
            service = MemoryItemInspectService(runner)
            items = service.items(person_id=person_id, limit=limit)
            envelope = memory_items_report(
                items,
                person_id=person_id,
                limit=limit,
                episode_conversion=service.episode_conversion(),
            )
            rendered["tailwag-memory-items.html"] = (memory_items_report_html(envelope), "text/html; charset=utf-8")
        elif report == "person_timeline":
            items = PersonTimelineRetrievalService(runner).items(person_id=person_id, limit=limit)
            envelope = _person_timeline_envelope(items, person_id=person_id, limit=limit)
            rendered["tailwag-person-timeline.html"] = (person_timeline_report_html(envelope), "text/html; charset=utf-8")
        else:
            raise ValueError(f"unknown report: {report!r}")

    if include_assets:
        rendered[INSPECT_CSS_FILENAME] = (inspect_asset_text(INSPECT_CSS_FILENAME), "text/css; charset=utf-8")
        rendered[INSPECT_JS_FILENAME] = (inspect_asset_text(INSPECT_JS_FILENAME), "application/javascript; charset=utf-8")
    return rendered


def publish_report_files(
    s3_client: Any,
    *,
    bucket: str,
    output_prefix: str,
    files: dict[str, tuple[str, str]],
) -> list[PublishedReport]:
    """Write rendered report files to S3."""
    prefix = output_prefix.strip("/")
    published: list[PublishedReport] = []
    for filename, (body, content_type) in files.items():
        key = f"{prefix}/{filename}" if prefix else filename
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType=content_type,
        )
        published.append(PublishedReport(key=key, content_type=content_type))
    return published


def _person_timeline_envelope(items: list[object], *, person_id: str | None, limit: int) -> InspectReport:
    return person_timeline_report(
        items,
        filters={
            "person_id": person_id,
            "limit": limit,
        },
        metadata={
            "utility": "inspect person-timeline",
            "storage": "read_only",
            "canonical_reports": {
                "person_timeline": "tailwag-person-timeline.html",
                "memory_items": "tailwag-memory-items.html",
            },
        },
        warnings=[] if items else ["No person timeline items matched the selected filters."],
    )
