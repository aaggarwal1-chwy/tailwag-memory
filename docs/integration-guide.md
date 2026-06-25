# Python Package Integration Guide

## Purpose

`tailwag-memory` is intended to be used by another Python repo as a package. The calling system owns IDs, identity decisions, biometric embedding generation, raw media handling, runtime orchestration, and retention policy. Tailwag owns durable Neo4j memory storage, embeddings, memory extraction/consolidation, retrieval, person context, and source adapters.

This guide stays at the package setup and integration-boundary level. For detailed command syntax, endpoint signatures, payload shapes, and source-adapter operation, use the focused references below.

## Reference Map

- Current graph model, scope, and deferred concepts: [Architecture](architecture.md)
- Python endpoints, parameters, input models, return shapes, and service constructors: [Memory Endpoints Reference](memory-endpoints.md)
- Local command examples and CLI workflow: [CLI Reference](cli-reference.md)
- Slack app setup, CLI polling, package-level polling, and Slack state behavior: [Slack Ingestion Guide](slack-ingestion.md)
- Argos replacement boundary, adapter contract, identity rules, and migration checklist: [Argos Migration Guide](argos-migration.md)

## Install From Another Local Repo

From the consuming repo, install Tailwag in editable mode:

```bash
python -m pip install -e /Users/aaggarwal1/Desktop/code/tailwag-memory
```

For local development with test dependencies:

```bash
python -m pip install -e "/Users/aaggarwal1/Desktop/code/tailwag-memory[dev]"
```

## Runtime Configuration

Set runtime configuration in the consuming process or its environment:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
export OPENAI_API_KEY=sk-your-token-here
export TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
export TAILWAG_EMBEDDING_DIMENSION=64
export TAILWAG_SYNTHESIS_MODEL=gpt-5.5
export SLACK_BOT_TOKEN=xoxb-your-token-here
```

Configuration notes:

- `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` are required for live storage and retrieval.
- `OPENAI_API_KEY` is required when production code uses OpenAI-backed text embeddings, memory extraction, consolidation, or vector search.
- `TAILWAG_EMBEDDING_DIMENSION` must match Neo4j vector indexes and supplied biometric vectors for vector search compatibility.
- `TAILWAG_SYNTHESIS_MODEL` controls the OpenAI model used by memory extraction and consolidation providers.
- `SLACK_BOT_TOKEN` is only required when polling Slack.

## Setup Sequence

1. Start or connect to a Neo4j database.
2. Install the Tailwag package in the consuming environment.
3. Set the runtime configuration above.
4. Initialize Tailwag's Neo4j schema once per database.
5. Use the high-level `TailwagMemoryClient` for normal package integration.
6. Use lower-level services only when you need dependency injection, custom providers, or offline tests.

See [Memory Endpoints Reference](memory-endpoints.md#runtime-setup) for schema initialization code and [CLI Reference](cli-reference.md#schema-and-local-data) for local command examples.

## Integration Responsibilities

The consuming system should provide:

- stable caller-owned `Person.id`, `Episode.id`, and `Event.id` values
- person identity and re-enrollment decisions
- consent status and retention policy
- face/audio embeddings from upstream recognition models, when available
- raw transcript, place, participant, and event payloads
- Slack channel IDs and bot credentials when using Slack ingestion

Tailwag provides:

- schema initialization for the approved Neo4j graph model
- episode, event, person, and memory item storage
- OpenAI-backed episode and memory item embeddings
- transcript-derived memory extraction and per-person memory consolidation
- graph, vector, biometric, and person-context retrieval
- Slack source adapter mapping into normal Tailwag episodes

## Public API Surface

Normal package consumers should start with:

```python
from tailwag_memory import TailwagMemoryClient
```

`TailwagMemoryClient` exposes the high-level calls for person profile updates, archiving, email-based rekeying, episode recording, memory extraction/backfill, memory consolidation, and prompt-ready person context. Detailed method signatures and return shapes live in [Memory Endpoints Reference](memory-endpoints.md#high-level-client-endpoints).

Lower-level services are public for advanced cases such as test fakes, custom embedding providers, source adapters, or direct memory item operations. Their constructor and method details also live in the endpoint reference.

Slack adapter classes are imported from `tailwag_memory.slack_ingestion`, not from the top-level package. See [Slack Ingestion Guide](slack-ingestion.md#package-api).

## Operational Notes

- Run schema initialization before ingestion or retrieval.
- Use caller-owned IDs; do not use Neo4j internal `<id>` or `<elementId>` values as integration keys.
- Do not pass raw face images or raw audio into Tailwag. Pass embeddings only.
- Keep biometric vector usage tied to consent and retention policies in the calling system.
- Direct memory item writes are advanced. Prefer episode recording plus extraction for live systems.
- `fact` memories must remain narrow person-prompt context, not broad ontology facts.
- `SemanticFact`, confidence fields, `org_id`, external vector stores, and secondary persistence are outside current scope.
