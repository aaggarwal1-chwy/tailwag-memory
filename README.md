# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and person context synthesis.

## Documentation

- [Repository agent instructions](AGENTS.md)
- [Concrete agent role cards](.agents/README.md)
- [Implementation plan](docs/implementation-plan.md)
- [Agent and subagent trigger matrix](docs/agent-trigger-matrix.md)
- [Python package integration guide](docs/integration-guide.md)
- [Slack ingestion guide](docs/slack-ingestion.md)

## Current Scope

Implemented now:

- `Person`
- `Episode`
- `Event`
- `Place`
- `PARTICIPATED_IN`
- `OCCURRED_AT`
- `ATTENDED`
- OpenAI-backed episode embeddings
- OpenAI-backed natural-language person context synthesis
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
- confidence ratings
- `org_id`
- Outlook/Microsoft Graph polling

## Local Setup

Start Neo4j:

```bash
docker compose up -d
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

For OpenAI-backed embeddings and person context synthesis, add your API key to the ignored repo-local `.env` file:

```bash
OPENAI_API_KEY=sk-your-token-here
```

For Slack polling, also add your bot token:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

For package usage, JSON payload shapes, retrieval examples, and command workflows, see the [Python package integration guide](docs/integration-guide.md). For Slack channel setup, polling state, and inspection queries, see the [Slack ingestion guide](docs/slack-ingestion.md).

Face and audio embeddings are biometric identifiers. The package stores vectors supplied by the calling system or an upstream recognition model; it does not store raw face images, raw audio, or generate real biometric embeddings itself.
Episode summaries and transcripts are sent to OpenAI for text embeddings. Recent event and episode context is sent to OpenAI when generating a natural-language person context paragraph. When `--semantic-scope` is provided for person context, the package first narrows evidence to vector-matched episodes for that person; unrelated recent history and events are not included.

## Tests

The tests can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
