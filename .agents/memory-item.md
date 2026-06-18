---
name: Memory Item Agent
slug: memory-item
primary_scope: Durable transcript-derived memory item semantics and behavior
main_outputs: memory item models, services, extraction contracts, context formatting, and tests
---

# Memory Item Agent

Use this agent when adding or changing durable transcript-derived memory items, memory item extraction, memory item context formatting, or memory item vector retrieval.

## Owns

- Memory item concepts and public behavior
- Future memory item models and services such as `src/tailwag_memory/memory_items.py`
- Memory item extraction operation contracts and validation
- Memory item context formatting for package consumers
- Memory item tests and examples

## Inputs

- Transcript or episode evidence that can support durable person memory
- Approved memory item kinds and lifecycle rules
- Existing person, episode, embedding, and retrieval contracts
- Argos-facing prompt context requirements when applicable

## Outputs

- `MemoryItem` model and service behavior
- Create, update, archive, and retrieval behavior for memory items
- Evidence links such as `(:Person)-[:HAS_MEMORY]->(:MemoryItem)` and `(:MemoryItem)-[:SUPPORTED_BY]->(:Episode)`
- Tests for memory item validation, dedupe, lifecycle, extraction, and context formatting

## Non-goals

- Owning all schema work when a focused Neo4j schema change is required
- Owning embedding provider internals
- Owning source-specific polling such as Slack API access
- Owning Argos repo migration code
- Implementing a broad ontology, triple store, or open-ended semantic fact graph

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_models tests.test_schema`
- `PYTHONPATH=src python3 -m unittest tests.test_ingestion tests.test_retrieval` when memory items affect write or read behavior
- Memory item extraction and formatting tests when those modules exist
- `PYTHONPATH=src python3 -m unittest discover -s tests` for broad memory item behavior changes

## Handoff

Hand off to the Neo4j Schema Agent for constraints, labels, relationships, or vector indexes.
Hand off to the OpenAI Embeddings Agent for embedding provider or vector generation behavior.
Hand off to the Retrieval Agent when memory item search or prompt context selection changes.
Hand off to the Integration Contract Agent when public package APIs or examples change.
Hand off to the Argos Migration Agent when behavior is driven by replacing `argos_src/memory`.
Bring in the Scope Guard Agent if memory item work risks expanding into a broad semantic ontology.
