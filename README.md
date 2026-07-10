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

Tailwag stores caller-owned people, places, episodes, events, directory rows,
biometric references, and transcript-derived memory items in Neo4j. It provides
OpenAI-backed text embeddings, graph/vector retrieval, prompt-ready and
structured person context, Slack ingestion, Snowflake/local directory sync,
optional FastAPI routes, and read-only inspect reports.

The authoritative implemented/deferred scope, graph model, relationship list,
and runtime configuration table live in [Architecture](docs/architecture.md).
Python APIs and optional HTTP route shapes live in
[Memory Endpoints Reference](docs/memory-endpoints.md), and command shapes live
in [CLI Reference](docs/cli-reference.md).

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
Use `--email-domain` with Snowflake username rows when Tailwag should synthesize
employee email addresses.

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

The inspection commands write static HTML reports under `inspect/` by default.
For generated assets, navigation, filters, and read-only boundaries, see the
[Inspect reference](docs/inspect-reference.md).

For the current graph model and scope boundaries, see the [architecture](docs/architecture.md). For the Python call surface and parameters, see the [memory endpoints reference](docs/memory-endpoints.md). For package setup and integration ownership, see the [Python package integration guide](docs/integration-guide.md). For local commands, see the [CLI reference](docs/cli-reference.md). For report outputs and inspect boundaries, see the [inspect reference](docs/inspect-reference.md). For Slack channel setup, polling state, and inspection queries, see the [Slack ingestion guide](docs/slack-ingestion.md). For the current Argos integration boundary, see the [Argos compatibility note](docs/argos-migration.md).

Face and voice embeddings are biometric identifiers. Tailwag stores vectors
supplied by the calling system or an upstream recognition model on biometric
reference nodes; it does not store raw face images, raw audio, or generate real
biometric embeddings itself. See [Architecture](docs/architecture.md) for
privacy and scope boundaries.

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
