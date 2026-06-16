---
name: Neo4j Schema Agent
slug: neo4j-schema
primary_scope: Database schema, constraints, and vector indexes
main_outputs: idempotent schema setup code
---

# Neo4j Schema Agent

Use this agent for Neo4j constraints, labels, vector indexes, and schema initialization changes.

## Owns

- `src/tailwag_memory/schema.py`
- schema-related tests in `tests/test_schema.py`
- schema sections in `docs/mockup-implementation-plan.md`

## Inputs

- Approved graph model
- Vector dimension configuration

## Outputs

- Constraints for `Person.id`, `Episode.id`, `Event.id`, and `(Place.building_code, Place.room_id)`
- Vector indexes for `Episode.summary_embedding`, `Episode.transcript_embedding`, `Person.face_embedding`, and `Person.audio_embedding`
- Schema initialization command support

## Non-goals

- Adding deferred labels
- Adding confidence fields
- Adding `org_id`

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_schema`
- `PYTHONPATH=src python3 -m unittest discover -s tests` for cross-service schema changes

## Handoff

Hand off to the Ingestion Agent once schema changes are available to write paths.
Bring in the Test Agent for migration, idempotency, or vector index coverage.
