from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

from ..models import PersonTimelineItem, utc_now_iso
from .models import PersonEpisodeAffectPoint


@dataclass(frozen=True)
class InspectReport:
    """Common report envelope for Tailwag inspect utilities."""

    title: str
    generated_at: str
    filters: dict[str, object] = field(default_factory=dict)
    records: list[dict[str, object]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def affect_report(
    points: list[PersonEpisodeAffectPoint],
    *,
    filters: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    warnings: list[str] | None = None,
) -> InspectReport:
    """Build a report envelope for affect scatter exports."""
    return InspectReport(
        title="Affect Scatter",
        generated_at=utc_now_iso(),
        filters=filters or {},
        records=[asdict(point) for point in points],
        metadata=metadata or {},
        warnings=warnings or [],
    )


def person_timeline_report(
    items: list[PersonTimelineItem],
    *,
    filters: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    warnings: list[str] | None = None,
) -> InspectReport:
    """Build a report envelope for person timeline exports."""
    return InspectReport(
        title="Person Timeline",
        generated_at=utc_now_iso(),
        filters=filters or {},
        records=[asdict(item) for item in items],
        metadata=metadata or {},
        warnings=warnings or [],
    )


def report_json(report: InspectReport) -> str:
    """Serialize an inspect report as stable JSON."""
    return json.dumps(asdict(report), indent=2, sort_keys=True)


def affect_report_html(report: InspectReport) -> str:
    """Render a self-contained affect scatter HTML report."""
    from .affect_report import affect_report_html as render

    return render(report)


def followup_validity_report_html(report: InspectReport) -> str:
    """Render a self-contained follow-up validity HTML report."""
    from .followup_report import followup_validity_report_html as render

    return render(report)


def memory_items_report_html(report: InspectReport) -> str:
    """Render a self-contained memory item inspection HTML report."""
    from .memory_report import memory_items_report_html as render

    return render(report)


def person_timeline_report_html(report: InspectReport) -> str:
    """Render a self-contained person timeline HTML report."""
    from .timeline_report import person_timeline_report_html as render

    return render(report)
