# CLI Reference

## Purpose

The `tailwag` command supports local schema setup, demo data, ingestion, retrieval, source-adapter polling, and memory maintenance. This reference lists command shapes for local development and smoke testing. For Python package APIs, see [Memory Endpoints Reference](memory-endpoints.md).

Most commands require Neo4j configuration. Commands that create episode embeddings, run memory extraction, run consolidation, or perform OpenAI-backed vector search also require OpenAI configuration.

## Schema And Local Data

Initialize the Neo4j schema:

```bash
tailwag schema init
```

Seed demo data:

```bash
tailwag seed demo
```

Wipe all Neo4j data before re-seeding:

```bash
tailwag db wipe --yes
```

## Episode And Event Ingestion

Create an episode from JSON without transcript memory extraction:

```bash
tailwag episode create --file examples/episode.json --skip-memory-extraction
```

Create an episode and run default transcript memory extraction:

```bash
tailwag episode create --file examples/episode.json
```

Create a later episode for an existing person by ID:

```bash
tailwag episode create --file examples/existing-person-episode.json
```

Create a place event with accepted attendees:

```bash
tailwag event create --file examples/event.json
```

## Retrieval

Search memories and related records:

```bash
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "chargers"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
tailwag event by-place --building-code MAIN --room-id 101
```

Generate prompt-ready person context:

```bash
tailwag person context --person-id person_jamie
tailwag person context --person-id person_jamie --semantic-scope "chargers"
tailwag person context --person-id person_jamie --current-text "robot demo later today"
tailwag person context --person-id person_jamie --memory-limit 8 --recent-episode-limit 3
```

Search people by caller-supplied biometric vectors:

```bash
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

## Memory Maintenance

Backfill or debug memory extraction for a stored episode:

```bash
tailwag memory extract --episode-id episode_example_001
tailwag memory extract --episode-id episode_example_001 --person-id person_jamie
```

Consolidate repeated or related person memory evidence:

```bash
tailwag memory consolidate --person-id person_jamie
tailwag memory consolidate --all --person-limit 100
tailwag memory consolidate --person-id person_jamie --min-evidence-episodes 4 --seed-limit 25 --neighbor-limit 12 --cluster-limit 8
```

## Slack Polling

Slack polling has additional app-scope and state-file behavior. See [Slack Ingestion Guide](slack-ingestion.md#poll-commands) for setup and full polling details.

Common local commands:

```bash
tailwag slack poll --channel C0123456789 --once
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill --skip-memory-extraction
tailwag slack poll --channel C0123456789 --interval 60
```

## Help

Every command exposes parser help:

```bash
tailwag --help
tailwag episode create --help
tailwag search --help
tailwag person context --help
tailwag memory consolidate --help
tailwag slack poll --help
```
