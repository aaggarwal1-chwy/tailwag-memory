from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Sequence

from .config import load_settings
from .db import Neo4jQueryRunner
from .embeddings import MockOpenAIEmbeddingProvider
from .ingestion import EpisodeIngestionService, EventIngestionService
from .models import EpisodeInput, EventInput, SearchQuery
from .retrieval import EpisodeRetrievalService, EventRetrievalService, PersonRecognitionService
from .schema import initialize_schema
from .slack_ingestion import SlackMemoryPoller, SlackWebApiClient


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tailwag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema")
    schema_subparsers = schema_parser.add_subparsers(dest="schema_command", required=True)
    schema_subparsers.add_parser("init")

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
    seed_subparsers.add_parser("demo")

    episode_parser = subparsers.add_parser("episode")
    episode_subparsers = episode_parser.add_subparsers(dest="episode_command", required=True)
    create_parser = episode_subparsers.add_parser("create")
    create_parser.add_argument("--file", required=True)

    event_parser = subparsers.add_parser("event")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)
    event_create_parser = event_subparsers.add_parser("create")
    event_create_parser.add_argument("--file", required=True)
    event_place_parser = event_subparsers.add_parser("by-place")
    event_place_parser.add_argument("--building-code", required=True)
    event_place_parser.add_argument("--room-id", required=True)
    event_place_parser.add_argument("--limit", type=int, default=10)

    person_parser = subparsers.add_parser("person")
    person_subparsers = person_parser.add_subparsers(dest="person_command", required=True)
    face_parser = person_subparsers.add_parser("search-face")
    face_parser.add_argument("--embedding-file", required=True)
    face_parser.add_argument("--limit", type=int, default=10)
    audio_parser = person_subparsers.add_parser("search-audio")
    audio_parser.add_argument("--embedding-file", required=True)
    audio_parser.add_argument("--limit", type=int, default=10)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("text")
    search_parser.add_argument("--person-id")
    search_parser.add_argument("--building-code")
    search_parser.add_argument("--room-id")
    search_parser.add_argument("--target", choices=["summary", "transcript"], default="summary")
    search_parser.add_argument("--limit", type=int, default=10)

    slack_parser = subparsers.add_parser("slack")
    slack_subparsers = slack_parser.add_subparsers(dest="slack_command", required=True)
    slack_poll_parser = slack_subparsers.add_parser("poll")
    slack_poll_parser.add_argument("--channel", required=True)
    slack_poll_parser.add_argument("--interval", type=float, default=60.0)
    slack_poll_parser.add_argument("--once", action="store_true")
    slack_poll_parser.add_argument("--state-file", default=".tailwag/slack-state.json")
    slack_poll_parser.add_argument("--backfill-hours", type=float)
    slack_poll_parser.add_argument("--active-thread-hours", type=float, default=24.0)
    slack_poll_parser.add_argument("--history-limit", type=int, default=200)
    slack_poll_parser.add_argument("--reply-limit", type=int, default=200)

    args = parser.parse_args(argv)
    if args.command == "db" and args.db_command == "wipe" and not args.yes:
        parser.error("db wipe requires --yes because it deletes all Neo4j data.")

    settings = load_settings()
    runner = Neo4jQueryRunner(settings)
    embeddings = MockOpenAIEmbeddingProvider(settings.embedding_dimension)

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

            seed_demo(runner, embeddings)
            print("Demo data seeded.")
            return 0

        if args.command == "episode":
            payload = json.loads(Path(args.file).read_text())
            service = EpisodeIngestionService(runner, embeddings)
            episode_id = service.ingest(EpisodeInput.from_dict(payload))
            print(f"Episode ingested: {episode_id}")
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
            service = EpisodeRetrievalService(runner, embeddings)
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
            if not settings.slack_bot_token:
                parser.error("SLACK_BOT_TOKEN is required. Add it to .env or export it in your shell.")

            service = EpisodeIngestionService(runner, embeddings)
            client = SlackWebApiClient(settings.slack_bot_token)
            poller = SlackMemoryPoller(
                client,
                service,
                Path(args.state_file),
                active_thread_hours=args.active_thread_hours,
            )

            while True:
                result = poller.poll_once(
                    args.channel,
                    backfill_hours=args.backfill_hours,
                    history_limit=args.history_limit,
                    reply_limit=args.reply_limit,
                )
                print(json.dumps(result.__dict__, sort_keys=True))
                if args.once:
                    return 0
                time.sleep(args.interval)

        return 2
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
