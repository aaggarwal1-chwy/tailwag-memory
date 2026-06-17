---
name: Ingestion Agent
slug: ingestion
primary_scope: Episode and event write paths
main_outputs: ingestion services, Cypher writes, ingestion tests
---

# Ingestion Agent

Use this agent when creating or updating episode memory records, place events, people, places, or write relationships.

## Owns

- `src/tailwag_memory/ingestion.py`
- write-path models in `src/tailwag_memory/models.py`
- ingestion tests in `tests/test_ingestion.py`
- ingestion examples in `examples/`

## Inputs

- Caller-provided `Episode.id`
- Caller-provided `Event.id`
- Caller-provided `Person.id`
- Participant roles and relationship provenance sources
- Optional caller-supplied face embeddings
- Optional caller-supplied audio embeddings
- Episode summary and transcript
- Event description and start/end times
- `building_code`
- `room_id`

## Outputs

- Persisted episode
- Persisted event
- Upserted people
- Updated `Person.last_seen`
- Stored `Person.face_embedding` when supplied
- Stored `Person.audio_embedding` when supplied
- Upserted place
- Graph relationships
- Episode embeddings

## Non-goals

- Semantic fact extraction
- Utterance segmentation
- Object or activity detection
- Retrieval ranking

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_ingestion`
- `PYTHONPATH=src python3 -m unittest tests.test_models tests.test_examples` when payload shape changes

## Handoff

Hand off to the Neo4j Schema Agent when writes require graph shape changes.
Hand off to the OpenAI Embeddings Agent when embedding behavior changes.
Hand off to the Retrieval Agent for query behavior created by new writes.
