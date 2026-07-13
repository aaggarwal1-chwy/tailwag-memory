# Python Package Integration Guide

## Purpose

`tailwag-memory` is intended to be used by another Python repo as a package. The calling system owns IDs, identity decisions, biometric embedding generation, raw media handling, runtime orchestration, and retention policy. Tailwag owns durable Neo4j memory storage, embeddings, memory extraction/consolidation, retrieval, person context, employee-directory row storage, and source adapters.

This guide stays at the package setup and integration-boundary level. For detailed command syntax, endpoint signatures, payload shapes, and source-adapter operation, use the focused references below.

## Reference Map

- Current graph model, scope, and deferred concepts: [Architecture](architecture.md)
- Python endpoints, parameters, input models, return shapes, and service constructors: [Memory Endpoints Reference](memory-endpoints.md)
- Local command examples and CLI workflow: [CLI Reference](cli-reference.md)
- Read-only local inspection reports and generated report assets: [Inspect Reference](inspect-reference.md)
- Slack app setup, CLI polling, package-level polling, and Slack state behavior: [Slack Ingestion Guide](slack-ingestion.md)
- Current Argos integration boundary and compatibility expectations: [Argos Compatibility Note](argos-migration.md)

## Install From Another Local Repo

From the consuming repo, install Tailwag in editable mode:

```bash
python -m pip install -e /Users/aaggarwal1/Desktop/code/tailwag-memory
```

For local affect inspection with external XLM-RoBERTa-large fold model directories:

```bash
python -m pip install -e "/Users/aaggarwal1/Desktop/code/tailwag-memory[affect]"
```

Other inspect reports use the base install. See [Inspect Reference](inspect-reference.md) for follow-up validity, person timeline, memory item, and affect report behavior.

## Runtime Configuration

Set runtime configuration in the consuming process or its environment:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
export OPENAI_API_KEY=sk-your-token-here
export TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
export TAILWAG_EMBEDDING_DIMENSION=64
export TAILWAG_FACE_EMBEDDING_DIMENSION=512
export TAILWAG_VOICE_EMBEDDING_DIMENSION=192
export TAILWAG_FACE_EMBEDDING_MODEL=facenet
export TAILWAG_VOICE_EMBEDDING_MODEL=speechbrain_ecapa
export TAILWAG_SYNTHESIS_MODEL=gpt-5.5
export SLACK_BOT_TOKEN=xoxb-your-token-here
export SNOWFLAKE_ACCOUNT=CHEWY-CHEWY
export SNOWFLAKE_USER=<username>@CHEWY.COM
export SNOWFLAKE_PASSWORD=
export SNOWFLAKE_AUTHENTICATOR=externalbrowser
export SNOWFLAKE_ROLE=X_EDLDB_USER
export SNOWFLAKE_WAREHOUSE=SNOWFLAKE_LEARNING_WH
export SNOWFLAKE_DATABASE=EDLDB
export SNOWFLAKE_SCHEMA=CHEWYBI
```

Configuration notes:

- `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` are required for live storage and retrieval.
- `OPENAI_API_KEY` is required when production code uses OpenAI-backed text embeddings, memory extraction, consolidation, or vector search.
- `TAILWAG_EMBEDDING_DIMENSION` must match Neo4j text vector indexes for episode and memory item embeddings.
- `TAILWAG_FACE_EMBEDDING_DIMENSION` and `TAILWAG_VOICE_EMBEDDING_DIMENSION` must match the configured face and voice reference vector indexes.
- `TAILWAG_FACE_EMBEDDING_MODEL` and `TAILWAG_VOICE_EMBEDDING_MODEL` identify the one supported upstream biometric model per modality. Tailwag stores those names on references and rejects adaptive updates when stored references were created with a different configured model.
- `TAILWAG_SYNTHESIS_MODEL` controls the OpenAI model used by memory extraction and consolidation providers.
- `SLACK_BOT_TOKEN` is only required when polling Slack.
- `SNOWFLAKE_*` variables are only required when using `sync_directory_from_snowflake()` or `tailwag directory sync` without `--file`. The Snowflake connector is currently a base package dependency because directory sync is part of the current CLI/API surface.
- `TAILWAG_AFFECT_FOLD1_MODEL` and `TAILWAG_AFFECT_FOLD2_MODEL` are optional paths used only by `tailwag inspect affect`.

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
- employee directory rows or Snowflake credentials when using Tailwag directory identity features
- face and voice embeddings from upstream recognition models, passed through Tailwag's biometric reference APIs when durable biometric state is intended
- raw transcript, place, participant, and event payloads
- Slack channel IDs and bot credentials when using Slack ingestion

Tailwag provides:

- schema initialization for the approved Neo4j graph model
- episode, event, person, and memory item storage
- OpenAI-backed episode and memory item embeddings
- transcript-derived memory extraction and per-person memory consolidation
- employee directory sync, fuzzy identity resolution, verified profile projection, and person encounter recording
- graph, vector, biometric, and person-context retrieval
- biometric reference enrollment/search and adaptive reference aggregation
- Slack source adapter mapping into normal Tailwag episodes

## Public API Surface

Normal package consumers should start with:

```python
from tailwag_memory import TailwagMemoryClient
```

`TailwagMemoryClient` exposes the high-level calls for person profile updates, archiving, email-based rekeying, directory sync and identity resolution, biometric reference enrollment/search/update, turn-owner resolution, episode recording, memory extraction/backfill, memory consolidation, prompt-ready and structured person context, and structured semantic search across a person's episodes and memory items. Detailed method signatures and return shapes live in [Memory Endpoints Reference](memory-endpoints.md#high-level-client-endpoints).

Lower-level services are public for advanced cases such as test fakes, custom embedding providers, source adapters, or direct memory item operations. Their constructor and method details also live in the endpoint reference.

Slack adapter classes are imported from `tailwag_memory.slack_ingestion`, not from the top-level package. See [Slack Ingestion Guide](slack-ingestion.md#package-api).

Inspection helpers are imported from `tailwag_memory.inspect`, not from the top-level package. They are intended for local investigation and reporting, not for normal memory-service integration.

## Operational Notes

- Run schema initialization before ingestion or retrieval.
- Use caller-owned IDs; do not use Neo4j internal `<id>` or `<elementId>` values as integration keys.
- Do not pass raw face images or raw audio into Tailwag. Pass embeddings only.
- Keep biometric vector usage tied to consent and retention policies in the calling system.
- Use `enroll_face_reference()` / `enroll_voice_reference()` for first durable samples, and `observe_face_embedding()` / `observe_voice_embedding()` for cross-modal-safe adaptive updates. Tailwag owns sample counts, similarity thresholds, and completion.
- Direct memory item writes are advanced. Prefer episode recording plus extraction for live systems.
- `fact` memories must remain narrow person-prompt context, not broad ontology facts.
- `SemanticFact`, confidence fields, `org_id`, external vector stores, and secondary persistence are outside current scope.
