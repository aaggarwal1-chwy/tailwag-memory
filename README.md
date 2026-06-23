# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and deterministic/vector-derived person context.

## Documentation

- [Repository agent instructions](AGENTS.md)
- [Project-scoped Codex custom agents](.codex/agents/)
- [Architecture](docs/architecture.md)
- [Argos migration guide](docs/argos-migration.md)
- [Agent and subagent trigger matrix](docs/agent-trigger-matrix.md)
- [Memory endpoints reference](docs/memory-endpoints.md)
- [Python package integration guide](docs/integration-guide.md)
- [CLI reference](docs/cli-reference.md)
- [Slack ingestion guide](docs/slack-ingestion.md)

## Current Scope

Implemented now:

- `Person`
- `Episode`
- `Event`
- `Place`
- `MemoryItem`
- `PARTICIPATED_IN`
- `OCCURRED_AT`
- `ATTENDED`
- `HAS_MEMORY`
- `SUPPORTED_BY`
- `SUPERSEDED_BY`
- OpenAI-backed episode embeddings
- OpenAI-backed memory item embeddings
- Neo4j 5.26 local Docker runtime
- Neo4j constraints and vector indexes for episode text, person biometric vectors, and `MemoryItem.summary_embedding`
- deterministic/vector-derived person context with durable memory sections and recent episode lines
- transcript-derived person memory items
- per-person memory consolidation and merged memories from repeated or related episode evidence into `MemoryItem`
- optional `Person.face_embedding`
- optional `Person.audio_embedding`
- graph and vector retrieval services
- Slack channel polling into conversation episodes
- source-provided event attendees

Delayed intentionally:

- `Robot`
- `ObjectConcept`
- `Activity`
- `Utterance`
- `SemanticFact`
- asynchronous semantic consolidation queue or orchestrator
- confidence ratings and confidence properties
- `org_id`
- external vector databases
- Postgres or other secondary persistence
- Outlook/Microsoft Graph polling and distribution list expansion

## Local Setup

Start Neo4j:

```bash
docker compose up -d
```

The local Compose runtime uses Neo4j 5.26.

Create a local env file from the template:

```bash
cp .env.example .env
```

Open Neo4j Browser:

```text
http://localhost:7474
```

Login with the local demo credentials:

```text
username: neo4j
password: tailwag-memory
```

Install the package in editable mode:

```bash
python3 -m pip install -e .
```

Initialize the Neo4j schema before ingesting or querying data:

```bash
tailwag schema init
```

For OpenAI-backed embeddings, transcript memory extraction, and memory consolidation, add your API key to the ignored repo-local `.env` file:

```bash
OPENAI_API_KEY=sk-your-token-here
```

Memory extraction and consolidation use `TAILWAG_SYNTHESIS_MODEL`, which defaults to the value in `.env.example`.

For Slack polling, also add your bot token:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

For the current graph model and scope boundaries, see the [architecture](docs/architecture.md). For the Python call surface and parameters, see the [memory endpoints reference](docs/memory-endpoints.md). For package setup and integration ownership, see the [Python package integration guide](docs/integration-guide.md). For local commands, see the [CLI reference](docs/cli-reference.md). For Slack channel setup, polling state, and inspection queries, see the [Slack ingestion guide](docs/slack-ingestion.md). For replacing Argos memory behavior, see the [Argos migration guide](docs/argos-migration.md).

Face and audio embeddings are biometric identifiers. The package stores vectors supplied by the calling system or an upstream recognition model; it does not store raw face images, raw audio, or generate real biometric embeddings itself.
Episode summaries, transcripts, and memory item summaries are sent to OpenAI for text embeddings when the OpenAI provider is configured. Person context is assembled deterministically from durable memory items, visible follow-ups, and recent episode lines. When `--semantic-scope` is provided for person context, the package uses vector matching to rank durable memory items; rendered episode context remains the bounded recent episode lines.
Memory item extraction sends caller-provided transcripts and a small set of existing candidate memory items to OpenAI when high-level episode recording or explicit memory backfill is used. Memory consolidation sends bounded, person-scoped episode evidence clusters and existing memory items to OpenAI. `MemoryItem` is the narrow approved semantic-memory path for durable person preferences, boundaries, pets, facts, and follow-ups; it is not a broad ontology or triple store.

## Tests

The tests can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
