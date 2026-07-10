# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and deterministic/vector-derived person context.

## Documentation

- [Repository agent instructions](AGENTS.md)
- [Project-scoped Codex custom agents](.codex/agents/)
- [Architecture](docs/architecture.md)
- [Argos compatibility note](docs/argos-migration.md)
- [Agent and subagent trigger matrix](docs/agent-trigger-matrix.md)
- [Memory endpoints reference](docs/memory-endpoints.md)
- [Python package integration guide](docs/integration-guide.md)
- [CLI reference](docs/cli-reference.md)
- [Inspect reference](docs/inspect-reference.md)
- [Slack ingestion guide](docs/slack-ingestion.md)

## Current Scope

Implemented now:

- `Person`
- `Episode`
- `Event`
- `Place`
- `MemoryItem`
- `EmployeeDirectoryRecord`
- `FaceReference`
- `VoiceReference`
- `PARTICIPATED_IN`
- `MENTIONED_IN`
- `OCCURRED_AT`
- `ATTENDED`
- `HAS_DIRECTORY_RECORD`
- `HAS_FACE_REFERENCE`
- `HAS_VOICE_REFERENCE`
- `HAS_MEMORY`
- `SUPPORTED_BY`
- `ADDRESSED_BY`
- `SUPERSEDED_BY`
- OpenAI-backed episode embeddings
- OpenAI-backed memory item embeddings
- Neo4j 5.26 local Docker runtime
- Neo4j constraints and vector indexes for episode text, biometric reference vectors, and `MemoryItem.summary_embedding`
- deterministic/vector-derived person context with durable memory sections and the target person's recent transcript lines
- transcript-derived person memory items
- per-person memory consolidation and merged memories from repeated or related episode evidence into `MemoryItem`
- `FaceReference` and `VoiceReference` nodes for caller-supplied biometric vectors
- adaptive biometric reference aggregation with per-reference sample counts
- graph and vector retrieval services
- Snowflake-backed employee directory sync and local JSON directory import
- Slack channel polling into conversation episodes
- source-provided event attendees
- optional read-only inspect reports for follow-up validity, affect, person timelines, and memory items

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

Install the optional FastAPI runtime when serving HTTP:

```bash
python3 -m pip install -e ".[api]"
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

For the HTTP API, add a bearer token. `GET /health` stays open for health checks;
all memory API routes require `Authorization: Bearer <token>`.

```bash
TAILWAG_API_BEARER_TOKEN=replace-with-a-private-token
```

Interactive FastAPI docs are off by default for production. Enable them only in local or controlled environments:

```bash
TAILWAG_API_DOCS_ENABLED=true
```

Run the API locally with Uvicorn:

```bash
python3 -m uvicorn tailwag_memory.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Or start the API container with the optional Compose profile:

```bash
docker compose --profile api up -d
```

Directory sync is part of the base package. `tailwag directory sync --site-code ...`
reads from Snowflake when no JSON file is supplied, using the `SNOWFLAKE_*`
variables in `.env.example`; `--file` imports local directory rows instead.

Optional inspection reports export read-only local HTML or JSON views:

```bash
tailwag inspect followup-validity
tailwag inspect person-timeline
tailwag inspect memory-items
```

The affect report also needs the optional dependency and external XLM-RoBERTa-large fold model directories:

```bash
python3 -m pip install -e ".[affect]"
tailwag inspect affect --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
```

The inspection commands write static HTML reports under `inspect/` by default. The committed report pages and index in that directory can be opened as static browser entry points, and regenerated reports link between follow-up validity, affect scatter, person timeline, and memory item views. HTML exports write `tailwag-inspect.css` and `tailwag-inspect.js` beside the report. Affect scores on demand, displays centered `-1..1` valence/arousal axes, supports drag-to-zoom for dense regions, and does not write affect values back to Neo4j.

For the current graph model and scope boundaries, see the [architecture](docs/architecture.md). For the Python call surface and parameters, see the [memory endpoints reference](docs/memory-endpoints.md). For package setup and integration ownership, see the [Python package integration guide](docs/integration-guide.md). For local commands, see the [CLI reference](docs/cli-reference.md). For report outputs and inspect boundaries, see the [inspect reference](docs/inspect-reference.md). For Slack channel setup, polling state, and inspection queries, see the [Slack ingestion guide](docs/slack-ingestion.md). For the current Argos integration boundary, see the [Argos compatibility note](docs/argos-migration.md).

Face and voice embeddings are biometric identifiers. The package stores vectors supplied by the calling system or an upstream recognition model on biometric reference nodes; it does not store raw face images, raw audio, or generate real biometric embeddings itself. Adaptive updates store sample counts and normalized running-average aggregates on those reference nodes.
Episode transcripts and memory item summaries are sent to OpenAI for text embeddings when the OpenAI provider is configured. Person context is assembled deterministically from durable memory items, visible follow-ups, and the target person's recent transcript lines. When `--semantic-scope` is provided for person context, the package uses vector matching to rank durable memory items; rendered episode context remains bounded to lines spoken by the target person.
Memory item extraction sends caller-provided transcripts and a small set of existing candidate memory items to OpenAI when high-level episode recording or explicit memory backfill is used. Memory consolidation sends bounded, person-scoped episode evidence clusters and existing memory items to OpenAI. `MemoryItem` is the narrow approved semantic-memory path for durable person preferences, boundaries, pets, facts, and follow-ups; it is not a broad ontology or triple store.

## Tests

The tests can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

API contract tests require the optional FastAPI runtime:

```bash
python3 -m pip install -e ".[api]"
PYTHONPATH=src python3 -m unittest tests.test_api_app
```
