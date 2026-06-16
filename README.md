# tailwag-memory

Neo4j-only hybrid memory mockup with mocked OpenAI-style embeddings.

## Planning Documents

- [Mockup implementation plan](docs/mockup-implementation-plan.md)
- [Agent and subagent trigger matrix](docs/agent-trigger-matrix.md)

## Current Mockup Scope

Implemented now:

- `Person`
- `Episode`
- `Place`
- `PARTICIPATED_IN`
- `OCCURRED_AT`
- mocked OpenAI-style episode embeddings
- optional `Person.face_embedding`
- optional `Person.audio_embedding`
- graph and vector retrieval services

Delayed intentionally:

- `Robot`
- `ObjectConcept`
- `Activity`
- `Utterance`
- `SemanticFact`
- confidence ratings
- `org_id`

## Local Setup

Start Neo4j:

```bash
docker compose up -d
```

Install the package in editable mode:

```bash
python3 -m pip install -e .
```

Initialize schema:

```bash
tailwag schema init
```

Seed demo data:

```bash
tailwag seed demo
```

Create an episode from JSON:

```bash
tailwag episode create --file examples/episode.json
```

Search memories:

```bash
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "chargers"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

Face and audio embeddings are biometric identifiers. The mockup stores vectors supplied by the calling system or an upstream recognition model; it does not store raw face images, raw audio, or generate real biometric embeddings itself.

## Tests

The tests can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
