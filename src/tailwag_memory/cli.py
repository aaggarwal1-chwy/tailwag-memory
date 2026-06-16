from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .config import load_settings
from .db import Neo4jQueryRunner
from .embeddings import MockOpenAIEmbeddingProvider
from .ingestion import EpisodeIngestionService
from .models import EpisodeInput, SearchQuery
from .retrieval import EpisodeRetrievalService, PersonRecognitionService
from .schema import initialize_schema


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tailwag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema")
    schema_subparsers = schema_parser.add_subparsers(dest="schema_command", required=True)
    schema_subparsers.add_parser("init")

    seed_parser = subparsers.add_parser("seed")
    seed_subparsers = seed_parser.add_subparsers(dest="seed_command", required=True)
    seed_subparsers.add_parser("demo")

    episode_parser = subparsers.add_parser("episode")
    episode_subparsers = episode_parser.add_subparsers(dest="episode_command", required=True)
    create_parser = episode_subparsers.add_parser("create")
    create_parser.add_argument("--file", required=True)

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

    args = parser.parse_args(argv)
    settings = load_settings()
    runner = Neo4jQueryRunner(settings)
    embeddings = MockOpenAIEmbeddingProvider(settings.embedding_dimension)

    try:
        if args.command == "schema":
            initialize_schema(runner, settings.embedding_dimension)
            print("Schema initialized.")
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

        return 2
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
