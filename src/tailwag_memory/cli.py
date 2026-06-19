from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Sequence

from .client import TailwagMemoryClient
from .config import Settings, load_settings
from .db import Neo4jQueryRunner
from .embeddings import MockOpenAIEmbeddingProvider, OpenAIEmbeddingProvider
from .ingestion import EventIngestionService
from .memory_items import (
    DEFAULT_CONSOLIDATION_CLUSTER_LIMIT,
    DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
    DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT,
    DEFAULT_CONSOLIDATION_SEED_LIMIT,
    DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
)
from .models import EpisodeInput, EventInput, SearchQuery
from .retrieval import EpisodeRetrievalService, EventRetrievalService, PersonRecognitionService
from .schema import initialize_schema
from .slack_ingestion import SlackMemoryPoller, SlackWebApiClient


def _embedding_provider(settings: Settings) -> OpenAIEmbeddingProvider:
    """Build the configured OpenAI embedding provider."""
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Tailwag command-line interface."""
    parser = argparse.ArgumentParser(prog="tailwag", description="Tailwag Neo4j memory service tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema")
    schema_subparsers = schema_parser.add_subparsers(dest="schema_command", required=True)
    schema_subparsers.add_parser("init", help="create Neo4j constraints and vector indexes")

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    wipe_parser = db_subparsers.add_parser("wipe")
    wipe_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm destructive deletion of all Neo4j nodes and relationships",
    )

    seed_parser = subparsers.add_parser("seed")
    seed_subparsers = seed_parser.add_subparsers(dest="seed_command", required=True)
    seed_subparsers.add_parser("demo", help="seed deterministic local demo data")

    episode_parser = subparsers.add_parser("episode")
    episode_subparsers = episode_parser.add_subparsers(dest="episode_command", required=True)
    create_parser = episode_subparsers.add_parser("create")
    create_parser.add_argument("--file", required=True, help="episode JSON payload path")
    create_parser.add_argument(
        "--skip-memory-extraction",
        action="store_true",
        help="store the episode without OpenAI-backed memory extraction",
    )

    event_parser = subparsers.add_parser("event")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)
    event_create_parser = event_subparsers.add_parser("create")
    event_create_parser.add_argument("--file", required=True, help="event JSON payload path")
    event_place_parser = event_subparsers.add_parser("by-place")
    event_place_parser.add_argument("--building-code", required=True, help="place building code")
    event_place_parser.add_argument("--room-id", required=True, help="place room id")
    event_place_parser.add_argument("--limit", type=int, default=10, help="maximum events to print")

    person_parser = subparsers.add_parser("person")
    person_subparsers = person_parser.add_subparsers(dest="person_command", required=True)
    face_parser = person_subparsers.add_parser("search-face")
    face_parser.add_argument("--embedding-file", required=True, help="JSON file containing the face embedding vector")
    face_parser.add_argument("--limit", type=int, default=10, help="maximum consented people to print")
    audio_parser = person_subparsers.add_parser("search-audio")
    audio_parser.add_argument("--embedding-file", required=True, help="JSON file containing the audio embedding vector")
    audio_parser.add_argument("--limit", type=int, default=10, help="maximum consented people to print")
    context_parser = person_subparsers.add_parser("context")
    context_parser.add_argument("--person-id", required=True, help="person id to summarize")
    context_parser.add_argument("--limit", type=int, default=10, help="maximum context items to retrieve")
    context_parser.add_argument("--semantic-scope", help="optional semantic focus for OpenAI-backed vector retrieval")
    context_parser.add_argument("--current-text", help="optional current utterance or task for memory item retrieval")
    context_parser.add_argument("--memory-limit", type=int, default=12, help="maximum durable memory items per section")
    context_parser.add_argument("--recent-episode-limit", type=int, default=5, help="maximum recent episode lines in memory context")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("text", help="query text")
    search_parser.add_argument("--person-id", help="optional person filter")
    search_parser.add_argument("--building-code", help="optional building filter")
    search_parser.add_argument("--room-id", help="optional room filter")
    search_parser.add_argument("--target", choices=["summary", "transcript"], default="summary", help="episode vector field")
    search_parser.add_argument("--limit", type=int, default=10, help="maximum episodes to print")

    slack_parser = subparsers.add_parser("slack")
    slack_subparsers = slack_parser.add_subparsers(dest="slack_command", required=True)
    slack_poll_parser = slack_subparsers.add_parser("poll")
    slack_poll_parser.add_argument("--channel", required=True, help="Slack channel id")
    slack_poll_parser.add_argument("--interval", type=float, default=60.0, help="seconds between continuous polls")
    slack_poll_parser.add_argument("--once", action="store_true", help="run one poll and exit")
    slack_poll_parser.add_argument("--state-file", default=".tailwag/slack-state.json", help="poll cursor state path")
    slack_poll_parser.add_argument("--backfill-hours", type=float, help="initial history window when no state exists")
    slack_poll_parser.add_argument(
        "--force-backfill",
        action="store_true",
        help="use --backfill-hours even when saved Slack polling state already exists",
    )
    slack_poll_parser.add_argument("--active-thread-hours", type=float, default=24.0, help="hours to keep checking recent roots")
    slack_poll_parser.add_argument("--history-limit", type=int, default=200, help="Slack history page size")
    slack_poll_parser.add_argument("--reply-limit", type=int, default=200, help="Slack replies page size")
    slack_poll_parser.add_argument("--skip-memory-extraction", action="store_true", help="store episodes without memory extraction")
    slack_poll_parser.add_argument("--include-email", action="store_true", help="store Slack profile email when available")

    memory_parser = subparsers.add_parser("memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_extract_parser = memory_subparsers.add_parser("extract")
    memory_extract_parser.add_argument("--episode-id", required=True, help="stored episode id")
    memory_extract_parser.add_argument("--person-id", help="limit extraction to one linked participant")
    memory_consolidate_parser = memory_subparsers.add_parser(
        "consolidate",
        help="consolidate repeated per-person episode evidence into memory items",
    )
    memory_consolidate_target = memory_consolidate_parser.add_mutually_exclusive_group(required=True)
    memory_consolidate_target.add_argument("--person-id", help="person id to consolidate")
    memory_consolidate_target.add_argument("--all", action="store_true", help="consolidate people with episode evidence")
    memory_consolidate_parser.add_argument("--person-limit", type=int, default=100, help="maximum people for --all")
    memory_consolidate_parser.add_argument(
        "--min-evidence-episodes",
        type=int,
        default=DEFAULT_MIN_PATTERN_EVIDENCE_EPISODES,
        help="minimum distinct supporting episodes required for a pattern",
    )
    memory_consolidate_parser.add_argument(
        "--seed-limit",
        type=int,
        default=DEFAULT_CONSOLIDATION_SEED_LIMIT,
        help="maximum recent episodes to use as vector-search seeds",
    )
    memory_consolidate_parser.add_argument(
        "--neighbor-limit",
        type=int,
        default=DEFAULT_CONSOLIDATION_NEIGHBOR_LIMIT,
        help="maximum vector neighbors to inspect per seed episode",
    )
    memory_consolidate_parser.add_argument(
        "--cluster-limit",
        type=int,
        default=DEFAULT_CONSOLIDATION_CLUSTER_LIMIT,
        help="maximum candidate clusters sent to the provider",
    )
    memory_consolidate_parser.add_argument(
        "--episode-text-limit",
        type=int,
        default=DEFAULT_CONSOLIDATION_EPISODE_TEXT_LIMIT,
        help="maximum summary/transcript characters per evidence episode",
    )
    memory_context_parser = memory_subparsers.add_parser("context")
    memory_context_parser.add_argument("--person-id", required=True, help="person id to summarize")
    memory_context_parser.add_argument("--limit", type=int, default=10, help="maximum context items to retrieve")
    memory_context_parser.add_argument("--semantic-scope", help="optional semantic focus for OpenAI-backed vector retrieval")
    memory_context_parser.add_argument("--current-text", help="optional current utterance or task for memory item retrieval")
    memory_context_parser.add_argument("--memory-limit", type=int, default=12, help="maximum durable memory items per section")
    memory_context_parser.add_argument(
        "--recent-episode-limit",
        type=int,
        default=5,
        help="maximum recent episode lines in memory context",
    )

    args = parser.parse_args(argv)
    if args.command == "db" and args.db_command == "wipe" and not args.yes:
        parser.error("db wipe requires --yes because it deletes all Neo4j data.")
    if args.command == "slack" and args.slack_command == "poll" and args.force_backfill and args.backfill_hours is None:
        parser.error("slack poll --force-backfill requires --backfill-hours.")
    if args.command == "slack" and args.slack_command == "poll" and args.force_backfill and not args.once:
        parser.error("slack poll --force-backfill requires --once so the same window is not replayed continuously.")

    settings = load_settings()
    if args.command == "slack" and args.slack_command == "poll" and not settings.slack_bot_token:
        parser.error("SLACK_BOT_TOKEN is required. Add it to .env or export it in your shell.")

    runner = Neo4jQueryRunner(settings)

    try:
        if args.command == "schema":
            initialize_schema(runner, settings.embedding_dimension)
            print("Schema initialized.")
            return 0

        if args.command == "db":
            runner.run("MATCH (n) DETACH DELETE n")
            print("Neo4j data wiped.")
            return 0

        if args.command == "seed":
            from .demo import seed_demo

            seed_demo(runner, MockOpenAIEmbeddingProvider(dimension=settings.embedding_dimension))
            print("Demo data seeded.")
            return 0

        if args.command == "episode":
            payload = json.loads(Path(args.file).read_text())
            client = TailwagMemoryClient(runner, settings)
            result = client.record_episode(
                EpisodeInput.from_dict(payload),
                extract_memory=not args.skip_memory_extraction,
            )
            print(json.dumps(asdict(result), sort_keys=True))
            return 0

        if args.command == "memory":
            client = TailwagMemoryClient(runner, settings)
            if args.memory_command == "context":
                print(
                    client.person_context(
                        args.person_id,
                        limit=args.limit,
                        semantic_scope=args.semantic_scope,
                        current_text=args.current_text,
                        memory_limit=args.memory_limit,
                        recent_episode_limit=args.recent_episode_limit,
                    )
                )
                return 0
            if args.memory_command == "consolidate":
                result = client.consolidate_memory(
                    person_id=args.person_id,
                    all_people=args.all,
                    person_limit=args.person_limit,
                    min_evidence_episodes=args.min_evidence_episodes,
                    seed_limit=args.seed_limit,
                    neighbor_limit=args.neighbor_limit,
                    cluster_limit=args.cluster_limit,
                    episode_text_limit=args.episode_text_limit,
                )
                print(json.dumps(asdict(result), sort_keys=True))
                return 0
            try:
                result = client.extract_memory_for_episode(
                    args.episode_id,
                    person_id=args.person_id,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print(json.dumps(asdict(result), sort_keys=True))
            return 0

        if args.command == "event":
            if args.event_command == "create":
                payload = json.loads(Path(args.file).read_text())
                service = EventIngestionService(runner)
                event_id = service.ingest(EventInput.from_dict(payload))
                print(f"Event ingested: {event_id}")
                return 0
            service = EventRetrievalService(runner)
            results = service.by_place(args.building_code, args.room_id, limit=args.limit)
            for result in results:
                print(json.dumps(result.__dict__, sort_keys=True))
            return 0

        if args.command == "person":
            if args.person_command == "context":
                client = TailwagMemoryClient(runner, settings)
                print(
                    client.person_context(
                        args.person_id,
                        limit=args.limit,
                        semantic_scope=args.semantic_scope,
                        current_text=args.current_text,
                        memory_limit=args.memory_limit,
                        recent_episode_limit=args.recent_episode_limit,
                    )
                )
                return 0

            embedding = json.loads(Path(args.embedding_file).read_text())
            service = PersonRecognitionService(runner)
            if args.person_command == "search-face":
                results = service.by_face_embedding(embedding, limit=args.limit)
            else:
                results = service.by_audio_embedding(embedding, limit=args.limit)
            for result in results:
                print(json.dumps(result.__dict__, sort_keys=True))
            return 0

        if args.command == "search":
            service = EpisodeRetrievalService(runner, _embedding_provider(settings))
            results = service.hybrid_search(
                SearchQuery(
                    text=args.text,
                    person_id=args.person_id,
                    building_code=args.building_code,
                    room_id=args.room_id,
                    limit=args.limit,
                    target=args.target,
                )
            )
            for result in results:
                print(json.dumps(result.__dict__, sort_keys=True))
            return 0

        if args.command == "slack":
            memory_client = TailwagMemoryClient(runner, settings)
            client = SlackWebApiClient(settings.slack_bot_token, include_email=args.include_email)
            poller = SlackMemoryPoller(
                client,
                memory_client,
                Path(args.state_file),
                active_thread_hours=args.active_thread_hours,
            )

            while True:
                result = poller.poll_once(
                    args.channel,
                    backfill_hours=args.backfill_hours,
                    force_backfill=args.force_backfill,
                    history_limit=args.history_limit,
                    reply_limit=args.reply_limit,
                    extract_memory=not args.skip_memory_extraction,
                )
                print(json.dumps(asdict(result), sort_keys=True))
                if args.once:
                    return 0
                time.sleep(args.interval)

        return 2
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
