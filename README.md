# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and person context synthesis.

## Planning Documents

- [Repository agent instructions](AGENTS.md)
- [Concrete agent role cards](.agents/README.md)
- [Implementation plan](docs/implementation-plan.md)
- [Agent and subagent trigger matrix](docs/agent-trigger-matrix.md)
- [Python package integration guide](docs/integration-guide.md)

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

For OpenAI-backed embeddings and person context synthesis, add your API key to the ignored repo-local file:

```text
/Users/aaggarwal1/Desktop/code/tailwag-memory/.env
```

Use this line:

```bash
OPENAI_API_KEY=sk-your-token-here
```

For Slack polling, also add your bot token:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

Initialize schema:

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

Create an episode from JSON:

```bash
tailwag episode create --file examples/episode.json
```

Create a later memory for an existing person by ID:

```bash
tailwag episode create --file examples/existing-person-episode.json
```

Create a place event with accepted attendees:

```bash
tailwag event create --file examples/event.json
```

Poll a Slack channel into memories:

```bash
tailwag slack poll --channel C0123456789 --once
```

The first run without `--backfill-hours` arms the cursor from the current time and does not import older messages. To test against recent existing channel activity, run:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
```

After wiping Neo4j data, force a backfill even if local Slack polling state already has a saved cursor:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
```

Run continuous polling:

```bash
tailwag slack poll --channel C0123456789 --interval 60
```

The Slack app must be invited to the channel. Public channel polling needs `channels:read`, `channels:history`, `users:read`, and `users:read.email`; private channels also need `groups:read` and `groups:history`.

See [Slack ingestion guide](docs/slack-ingestion.md) for channel ID discovery, polling state, and inspection queries.

Search memories:

```bash
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "chargers"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
tailwag event by-place --building-code MAIN --room-id 101
tailwag person context --person-id person_jamie
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

Face and audio embeddings are biometric identifiers. The package stores vectors supplied by the calling system or an upstream recognition model; it does not store raw face images, raw audio, or generate real biometric embeddings itself.
Episode summaries and transcripts are sent to OpenAI for text embeddings. Recent event and episode context is sent to OpenAI when generating a natural-language person context paragraph.

## Tests

The tests can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
