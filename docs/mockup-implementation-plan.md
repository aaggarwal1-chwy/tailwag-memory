# Neo4j-Only Memory Mockup Implementation Plan

## Goal

Build a small Neo4j-only memory mockup that proves the core loop:

1. Accept caller-owned people, places, and episode inputs.
2. Store each interaction as an `Episode`.
3. Connect episodes to participating people and places.
4. Generate mocked OpenAI-style embeddings for episode text.
5. Retrieve memories through graph lookups and Neo4j vector search.

This mockup should be narrow, inspectable, and easy to extend later.

## Current Scope

Implemented now:

- `Person`
- `Episode`
- `Place`
- `PARTICIPATED_IN`
- `OCCURRED_AT`
- mocked OpenAI embedding responses
- optional caller-supplied person face embeddings
- optional caller-supplied person audio embeddings
- Neo4j constraints and vector indexes
- ingestion flow
- retrieval flow
- seed/demo data
- tests
- CLI-first local workflow

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

## Design Decisions

- Do not store confidence ratings in the mockup.
- Do not store `org_id` anywhere in the mockup.
- `Person.id` is supplied by the calling system.
- `Episode.id` is supplied by the calling system.
- `Place` is identified only by `building_code` and `room_id`.
- Embeddings should use an OpenAI-compatible interface, but the mockup should return deterministic fake embeddings for now.
- The code should be split early enough to avoid large, tangled modules.

## Initial Graph Model

### Person

```cypher
(:Person {
  id,
  display_name,
  consent_status,
  face_embedding,
  audio_embedding,
  last_seen,
  created_at
})
```

Notes:

- `id` comes from the calling system.
- `last_seen` is updated when the person participates in a newer episode.
- `identity_status` is intentionally excluded.
- `face_embedding` and `audio_embedding` are optional biometric vectors supplied by the calling system or upstream recognition models.
- Raw face images and raw audio are not stored by this mockup.

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
  visibility,
  created_at,
  summary_embedding,
  transcript_embedding
})
```

Notes:

- `id` comes from the calling system.
- `summary_embedding` and `transcript_embedding` are mocked OpenAI-style vectors in the initial implementation.
- Raw recordings are not stored.

### Place

```cypher
(:Place {
  building_code,
  room_id
})
```

Notes:

- The mockup uses only `building_code` and `room_id`.
- Later place enrichment can add properties such as names, maps, floors, and coordinates without changing the episode-to-place relationship.

## Initial Relationships

```cypher
(:Person)-[:PARTICIPATED_IN {
  role,
  source
}]->(:Episode)

(:Episode)-[:OCCURRED_AT]->(:Place)
```

## Constraints

```cypher
CREATE CONSTRAINT person_id IF NOT EXISTS
FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT episode_id IF NOT EXISTS
FOR (e:Episode) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT place_key IF NOT EXISTS
FOR (p:Place) REQUIRE (p.building_code, p.room_id) IS UNIQUE;
```

## Vector Indexes

Create vector indexes for:

- `Episode.summary_embedding`
- `Episode.transcript_embedding`
- `Person.face_embedding`
- `Person.audio_embedding`

The embedding dimension should be configurable so the mock provider and future OpenAI provider can share the same retrieval code.

## Embedding Interface

Use an interface like:

```python
class EmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        ...
```

Initial implementation:

```text
MockOpenAIEmbeddingProvider
```

Requirements:

- deterministic for repeatable tests
- same vector dimension as configured for the mockup
- no network calls
- shaped so a future `OpenAIEmbeddingProvider` can replace it without changing ingestion or retrieval

## Proposed Project Layout

```text
tailwag-memory/
  README.md
  docker-compose.yml
  .env.example
  pyproject.toml
  docs/
    mockup-implementation-plan.md
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

### Phase 3: Mock Embeddings

- Add the embedding provider interface.
- Add deterministic mocked OpenAI embeddings.
- Add tests that verify stable output shape and deterministic behavior.

### Phase 4: Ingestion

- Accept caller-provided person IDs and episode IDs.
- Upsert `Person` nodes.
- Update `Person.last_seen`.
- Upsert `Place` nodes by `building_code` and `room_id`.
- Create or update `Episode` nodes.
- Attach `PARTICIPATED_IN` and `OCCURRED_AT`.

### Phase 5: Retrieval

- Retrieve episodes by person.
- Retrieve episodes by place.
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

## CLI Mockup Commands

Target command shape:

```bash
tailwag schema init
tailwag seed demo
tailwag episode create --file examples/episode.json
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "charger"
tailwag search --building-code MAIN --room-id 101 "projector"
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

The mockup should not create these nodes or relationships yet.
