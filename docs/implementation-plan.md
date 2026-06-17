# Neo4j-Only Memory Implementation Plan

## Goal

Build a compact Neo4j-only memory service that proves the core loop:

1. Accept caller-owned people, places, episode inputs, and event inputs.
2. Store each interaction as an `Episode`.
3. Store place-linked happenings as `Event`.
4. Connect episodes to participating people and places.
5. Connect events to places and accepted attendees.
6. Generate OpenAI-backed embeddings for episode text while keeping tests mocked.
7. Retrieve memories through graph lookups and Neo4j vector search.

This project should remain narrow, inspectable, and easy to extend.

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
- optional caller-supplied person face embeddings
- optional caller-supplied person audio embeddings
- Neo4j constraints and vector indexes
- ingestion flow
- retrieval flow
- seed/demo data
- tests
- CLI-first local workflow
- Slack channel polling as a source adapter into conversation episodes
- event attendee relationships for source-provided accepted attendees

Deferred for later:

- `Robot`
- `ObjectConcept`
- `Activity`
- `Utterance`
- `SemanticFact`
- semantic consolidation queue
- confidence ratings and confidence properties
- external vector databases
- Postgres or other secondary persistence
- Outlook/Microsoft Graph polling and distribution list expansion

## Design Decisions

- Do not store confidence ratings in the current scope.
- Do not store `org_id` anywhere in the current scope.
- `Person.id` is supplied by the calling system.
- `Episode.id` is supplied by the calling system.
- `Event.id` is supplied by the calling system.
- `Place` is identified only by `building_code` and `room_id`.
- Embeddings should use an OpenAI-compatible interface, while the current implementation returns deterministic fake embeddings.
- The code should be split early enough to avoid large, tangled modules.

## Initial Graph Model

### Person

```cypher
(:Person {
  id,
  display_name,
  email,
  consent_status,
  face_embedding,
  audio_embedding,
  last_seen,
  created_at
})
```

Notes:

- `id` comes from the calling system.
- `email` is optional identity evidence for future linking; it is not the unique person key.
- `last_seen` is updated when the person participates in a newer episode.
- `identity_status` is intentionally excluded.
- `face_embedding` and `audio_embedding` are optional biometric vectors supplied by the calling system or upstream recognition models.
- Raw face images and raw audio are not stored by this package.
- On first encounter, the caller should provide consent/profile data. Later episode payloads can reference the existing person by `id` only.

### Episode

```cypher
(:Episode {
  id,
  episode_type,
  start_time,
  end_time,
  summary,
  transcript,
  retention_class,
  created_at,
  summary_embedding,
  transcript_embedding
})
```

Notes:

- `id` comes from the calling system.
- `summary_embedding` and `transcript_embedding` are OpenAI-backed vectors in production and deterministic mock vectors in tests.
- Raw recordings are not stored.

### Event

```cypher
(:Event {
  id,
  description,
  start_time,
  end_time,
  created_at
})
```

Notes:

- `id` comes from the calling system.
- Events represent something that happened, is happening, or is scheduled to happen in a place.
- Events can reference accepted attendees through `ATTENDED`.
- Events are linked to `Place` through `OCCURRED_AT`.

### Place

```cypher
(:Place {
  building_code,
  room_id
})
```

Notes:

- The system uses only `building_code` and `room_id`.
- Later place enrichment can add properties such as names, maps, floors, and coordinates without changing the episode-to-place relationship.

## Initial Relationships

```cypher
(:Person)-[:PARTICIPATED_IN {
  role,
  source
}]->(:Episode)

(:Episode)-[:OCCURRED_AT]->(:Place)

(:Event)-[:OCCURRED_AT]->(:Place)

(:Person)-[:ATTENDED {
  source,
  response,
  response_time
}]->(:Event)
```

`PARTICIPATED_IN.source` records how the calling system decided the person participated in the episode. Example values include `face_recognition`, `speaker_recognition`, `manual`, `caller`, `demo`, or `example`. It is provenance for the relationship, not a confidence score. If multiple signals are used later, the caller can choose a combined value such as `face_and_audio` or the model can be expanded to store richer evidence.

`ATTENDED.source` records how the calling system determined that the person attended or accepted an event. For Outlook-derived events, a later adapter can use `source="outlook"` and `response="accepted"`.

## Neo4j Browser IDs

Neo4j Browser shows internal identity fields such as `<id>` and `<elementId>` in addition to this project's `id` property.

- `<id>` is Neo4j's legacy internal numeric node or relationship ID.
- `<elementId>` is Neo4j's internal string identifier for a graph element.
- `id` is the application-level identifier supplied by the calling system.

Application code should use the `id` property for `Person` and `Episode`. Do not store or depend on Neo4j internal IDs, because they are database implementation details and are not good cross-system identifiers.

## Constraints

```cypher
CREATE CONSTRAINT person_id IF NOT EXISTS
FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT episode_id IF NOT EXISTS
FOR (e:Episode) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT event_id IF NOT EXISTS
FOR (e:Event) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT place_key IF NOT EXISTS
FOR (p:Place) REQUIRE (p.building_code, p.room_id) IS UNIQUE;
```

## Vector Indexes

Create vector indexes for:

- `Episode.summary_embedding`
- `Episode.transcript_embedding`
- `Person.face_embedding`
- `Person.audio_embedding`

The embedding dimension should be configurable so the OpenAI provider and deterministic mock provider can share the same retrieval code.

## Embedding Interface

Use an interface like:

```python
class EmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        ...
```

Production implementation:

```text
OpenAIEmbeddingProvider
```

Requirements:

- deterministic mock provider for repeatable tests
- same vector dimension as configured for the service
- no network calls in tests
- OpenAI-backed runtime embeddings without changing ingestion or retrieval service APIs

## Proposed Project Layout

```text
tailwag-memory/
  README.md
  docker-compose.yml
  .env.example
  pyproject.toml
  docs/
    implementation-plan.md
    agent-trigger-matrix.md
  src/tailwag_memory/
    __init__.py
    config.py
    db.py
    schema.py
    models.py
    embeddings.py
    ingestion.py
    retrieval.py
    cli.py
  scripts/
    reset_neo4j.py
    seed_demo.py
  examples/
    episode.json
  tests/
    test_schema.py
    test_models.py
    test_embeddings.py
    test_ingestion.py
    test_retrieval.py
```

## Implementation Phases

### Phase 1: Scaffold

- Add Python package metadata.
- Add Docker Compose for local Neo4j.
- Add `.env.example`.
- Add package folders and test folders.

### Phase 2: Schema

- Add idempotent schema setup.
- Add uniqueness constraints.
- Add vector indexes.

### Phase 3: Embeddings

- Add the embedding provider interface.
- Add OpenAI-backed production embeddings.
- Keep deterministic mocked OpenAI embeddings for tests.
- Add tests that verify stable output shape, dimensions, and mock determinism.

### Phase 4: Ingestion

- Accept caller-provided person IDs, episode IDs, and event IDs.
- Upsert `Person` nodes.
- Update `Person.last_seen`.
- Upsert `Place` nodes by `building_code` and `room_id`.
- Create or update `Episode` nodes.
- Attach `PARTICIPATED_IN` and `OCCURRED_AT`.
- Create or update `Event` nodes.
- Attach events to places with `OCCURRED_AT`.
- Attach accepted event attendees with `ATTENDED`.

### Phase 5: Retrieval

- Retrieve episodes by person.
- Retrieve episodes by place.
- Retrieve events by place.
- Retrieve episodes by summary vector similarity.
- Retrieve episodes by transcript vector similarity.
- Add a hybrid query path that combines optional graph filters with vector search.

### Phase 6: Demo Workflow

- Add seed data.
- Add CLI commands for schema setup, seeding, ingestion, and search.
- Keep examples small enough to inspect manually in Neo4j Browser.

### Phase 7: Tests

- Test schema setup.
- Test caller-owned IDs.
- Test `last_seen` updates.
- Test place uniqueness.
- Test graph retrieval.
- Test mocked vector retrieval.

### Phase 8: Refactor Pass

- Split any oversized modules.
- Consolidate duplicated Cypher.
- Keep provider boundaries clear.
- Ensure deferred concepts can be added without rewriting ingestion and retrieval.

## CLI Commands

Target command shape:

```bash
tailwag schema init
tailwag seed demo
tailwag episode create --file examples/episode.json
tailwag event create --file examples/event.json
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "charger"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag event by-place --building-code MAIN --room-id 101
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

Person recognition commands expect JSON files containing embedding vectors. This mirrors a deployment where a camera/audio pipeline generates face or speaker embeddings before calling the memory service.

## Future Extension Path

Later concepts should be added as parallel modules and schema sections:

- `robot.py`
- `object_concept.py`
- `activity.py`
- `utterance.py`
- `semantic_fact.py`

Expected future relationships:

- `(:Robot)-[:OBSERVED_OR_HANDLED]->(:Episode)`
- `(:Episode)-[:MENTIONED]->(:ObjectConcept)`
- `(:Episode)-[:HAS_ACTIVITY]->(:Activity)`
- `(:Episode)-[:CONTAINS]->(:Utterance)`
- `(:SemanticFact)-[:SUPPORTED_BY]->(:Episode)`

The current implementation should not create these nodes or relationships yet.
