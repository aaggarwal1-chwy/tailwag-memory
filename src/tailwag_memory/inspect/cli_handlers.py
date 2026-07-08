from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from ..config import Settings
from ..db import QueryRunner
from . import (
    AffectScoringConfigurationError,
    FoldEnsembleAffectProvider,
    FollowupValidityInspectService,
    MemoryItemInspectService,
    PersonEpisodeTranscriptService,
    PersonTimelineRetrievalService,
    affect_report,
    affect_report_html,
    followup_validity_report,
    followup_validity_report_html,
    memory_items_report,
    memory_items_report_html,
    person_timeline_report,
    person_timeline_report_html,
    report_json,
    score_transcript_points,
)
from .html_utils import INSPECT_CSS_FILENAME, INSPECT_JS_FILENAME, INSPECT_SHARED_CSS, INSPECT_SHARED_JS

ReportWriter = Callable[[str, str | None], None]
ParserError = Callable[[str], None]


def add_inspect_subcommands(inspect_subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register inspect subcommands on the CLI parser."""

    affect_parser = inspect_subparsers.add_parser("affect", help="export person-episode valence/arousal inspection data")
    affect_parser.add_argument("--person-id", help="optional person filter")
    affect_parser.add_argument("--limit", type=int, default=1000, help="maximum person-episode pairs to score")
    affect_parser.add_argument("--format", choices=["html", "json"], default="html", help="export format")
    affect_parser.add_argument("--output", help="output file path, or '-' for stdout")
    affect_parser.add_argument("--fold1-model", help="external XLM-RoBERTa-large fold1 model directory")
    affect_parser.add_argument("--fold2-model", help="external XLM-RoBERTa-large fold2 model directory")

    followup_validity_parser = inspect_subparsers.add_parser(
        "followup-validity",
        help="export follow-ups grouped by validity duration",
    )
    followup_validity_parser.add_argument("--limit", type=int, default=1000, help="maximum follow-up items to export")
    followup_validity_parser.add_argument("--format", choices=["html", "json"], default="html", help="export format")
    followup_validity_parser.add_argument("--output", help="output file path, or '-' for stdout")

    person_timeline_parser = inspect_subparsers.add_parser(
        "person-timeline",
        help="export read-only person timeline inspection data",
    )
    person_timeline_parser.add_argument("--person-id", help="optional person filter")
    person_timeline_parser.add_argument("--limit", type=int, default=100, help="maximum timeline items to export")
    person_timeline_parser.add_argument("--format", choices=["html", "json"], default="html", help="export format")
    person_timeline_parser.add_argument("--output", help="output file path, or '-' for stdout")

    memory_items_parser = inspect_subparsers.add_parser(
        "memory-items",
        help="export read-only memory item inspection data",
    )
    memory_items_parser.add_argument("--person-id", help="optional person filter")
    memory_items_parser.add_argument("--limit", type=int, default=1000, help="maximum memory items to export")
    memory_items_parser.add_argument("--format", choices=["html", "json"], default="html", help="export format")
    memory_items_parser.add_argument("--output", help="output file path, or '-' for stdout")


def validate_inspect_args(args: argparse.Namespace, settings: Settings, parser_error: ParserError) -> None:
    """Validate inspect args that must fail before opening external resources."""

    if args.command == "inspect" and args.inspect_command == "affect":
        try:
            args.affect_model_dirs = _resolve_affect_model_dirs(args, settings)
        except ValueError as exc:
            parser_error(str(exc))


def run_inspect_command(
    args: argparse.Namespace,
    *,
    runner: QueryRunner,
    writer: ReportWriter,
    parser_error: ParserError,
) -> int:
    """Run one inspect subcommand."""

    if args.inspect_command == "followup-validity":
        items = FollowupValidityInspectService(runner).items(limit=args.limit)
        report = followup_validity_report(items, limit=args.limit)
        rendered = report_json(report) if args.format == "json" else followup_validity_report_html(report)
        output = _output_path(args, "inspect/tailwag-followup-validity.html")
        writer(rendered, output)
        _write_shared_assets(args, output)
        return 0

    if args.inspect_command == "affect":
        affect_model_dirs = args.affect_model_dirs
        points = PersonEpisodeTranscriptService(runner).points(
            person_id=args.person_id,
            limit=args.limit,
        )
        try:
            provider = FoldEnsembleAffectProvider.from_model_dirs(*affect_model_dirs)
            scored_points = score_transcript_points(points, provider)
        except AffectScoringConfigurationError as exc:
            parser_error(str(exc))
        report = affect_report(
            scored_points,
            filters={
                "person_id": args.person_id,
                "limit": args.limit,
            },
            metadata={
                "utility": "inspect affect",
                "storage": "on_demand",
                "future_storage_hint": "person-to-episode or person-to-memory relationship properties",
                "fold1_model": affect_model_dirs[0],
                "fold2_model": affect_model_dirs[1],
            },
            warnings=[] if points else ["No person-specific transcript text matched the selected filters."],
        )
        rendered = report_json(report) if args.format == "json" else affect_report_html(report)
        output = _output_path(args, "inspect/tailwag-affect.html")
        writer(rendered, output)
        _write_shared_assets(args, output)
        return 0

    if args.inspect_command == "person-timeline":
        items = PersonTimelineRetrievalService(runner).items(
            person_id=args.person_id,
            limit=args.limit,
        )
        report = person_timeline_report(
            items,
            filters={
                "person_id": args.person_id,
                "limit": args.limit,
            },
            metadata={
                "utility": "inspect person-timeline",
                "storage": "read_only",
                "canonical_reports": {
                    "person_timeline": "tailwag-person-timeline.html",
                    "affect": "tailwag-affect.html",
                    "memory_items": "tailwag-memory-items.html",
                },
            },
            warnings=[] if items else ["No person timeline items matched the selected filters."],
        )
        rendered = report_json(report) if args.format == "json" else person_timeline_report_html(report)
        output = _output_path(args, "inspect/tailwag-person-timeline.html")
        writer(rendered, output)
        _write_shared_assets(args, output)
        return 0

    if args.inspect_command == "memory-items":
        service = MemoryItemInspectService(runner)
        items = service.items(
            person_id=args.person_id,
            limit=args.limit,
        )
        episode_conversion = service.episode_conversion()
        report = memory_items_report(
            items,
            person_id=args.person_id,
            limit=args.limit,
            episode_conversion=episode_conversion,
        )
        rendered = report_json(report) if args.format == "json" else memory_items_report_html(report)
        output = _output_path(args, "inspect/tailwag-memory-items.html")
        writer(rendered, output)
        _write_shared_assets(args, output)
        return 0

    return 2


def _output_path(args: argparse.Namespace, default_html_path: str) -> str | None:
    """Return the CLI output path, using default HTML output when omitted."""

    output = args.output
    if output is None and args.format == "html":
        output = default_html_path
    return None if output == "-" else output


def _write_shared_assets(args: argparse.Namespace, output: str | None) -> None:
    """Write shared inspect browser assets beside generated HTML reports."""

    if args.format != "html" or output is None:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.with_name(INSPECT_CSS_FILENAME).write_text(INSPECT_SHARED_CSS)
    output_path.with_name(INSPECT_JS_FILENAME).write_text(INSPECT_SHARED_JS)


def _resolve_affect_model_dirs(args: argparse.Namespace, settings: Settings) -> tuple[str, str]:
    """Resolve fold model directories from CLI args or environment-backed settings."""

    fold1_model = str(args.fold1_model or settings.affect_fold1_model or "").strip()
    fold2_model = str(args.fold2_model or settings.affect_fold2_model or "").strip()
    if not fold1_model:
        raise ValueError("--fold1-model or TAILWAG_AFFECT_FOLD1_MODEL is required")
    if not fold2_model:
        raise ValueError("--fold2-model or TAILWAG_AFFECT_FOLD2_MODEL is required")
    for label, value in [("fold1", fold1_model), ("fold2", fold2_model)]:
        path = Path(value)
        if not path.exists() or not path.is_dir():
            raise ValueError(f"{label} model directory does not exist: {value}")
    return fold1_model, fold2_model
