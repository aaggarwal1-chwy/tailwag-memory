---
name: OpenAI Embeddings Agent
slug: openai-embeddings
primary_scope: Embedding interface, OpenAI runtime provider, and deterministic mock provider
main_outputs: provider interface, OpenAI embeddings, mock vectors, embedding tests
---

# OpenAI Embeddings Agent

Use this agent when embedding generation, embedding dimensions, or provider boundaries change.

## Owns

- `src/tailwag_memory/embeddings.py`
- embedding-related config interactions
- `tests/test_embeddings.py`

## Inputs

- Text to embed
- Configured vector dimension

## Outputs

- OpenAI-backed production embeddings
- Deterministic fake embeddings for tests
- Provider interface
- Tests proving stable dimensions and deterministic outputs

## Non-goals

- Choosing a production model
- Adding non-episode embedding targets

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_embeddings`
- `PYTHONPATH=src python3 -m unittest tests.test_retrieval` when vector query behavior changes

## Handoff

Hand off to the Ingestion Agent and Retrieval Agent when provider behavior affects stored or queried vectors.
Bring in the Code Refactor Agent if provider logic leaks into service or CLI modules.
