---
name: Retrieval Agent
slug: retrieval
primary_scope: Graph and vector read paths
main_outputs: retrieval services, hybrid search, retrieval tests
---

# Retrieval Agent

Use this agent for person, place, event, vector, biometric, or hybrid memory search behavior.

## Owns

- `src/tailwag_memory/retrieval.py`
- read-path models in `src/tailwag_memory/models.py`
- retrieval tests in `tests/test_retrieval.py`

## Inputs

- Natural language query text
- Face embedding vector
- Audio embedding vector
- Optional `person_id`
- Optional `building_code`
- Optional `room_id`
- Optional retrieval limit

## Outputs

- Matching episode IDs
- Matching event IDs for place event queries
- Matching person IDs for biometric queries
- Summaries
- Transcript snippets
- Vector scores where applicable

## Non-goals

- Writes
- Data import
- Semantic consolidation

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_retrieval`
- `PYTHONPATH=src python3 -m unittest tests.test_ingestion` when reads depend on new write shape

## Handoff

Hand off to the Ingestion Agent if missing writes block retrieval behavior.
Hand off to the CLI Mockup Agent when read behavior needs a developer command.
Bring in the Test Agent for ranking, filtering, or query fallback coverage.
