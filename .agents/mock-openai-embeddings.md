---
name: Mock OpenAI Embeddings Agent
slug: mock-openai-embeddings
primary_scope: Embedding interface and deterministic mock provider
main_outputs: provider interface, mock vectors, embedding tests
---

# Mock OpenAI Embeddings Agent

Use this agent when embedding generation, embedding dimensions, or provider boundaries change.

## Owns

- `src/tailwag_memory/embeddings.py`
- embedding-related config interactions
- `tests/test_embeddings.py`

## Inputs

- Text to embed
- Configured vector dimension

## Outputs

- Deterministic fake embeddings
- Provider interface
- Tests proving stable dimensions and deterministic outputs

## Non-goals

- Calling the OpenAI API
- Choosing a production model
- Adding non-episode embedding targets

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_embeddings`
- `PYTHONPATH=src python3 -m unittest tests.test_retrieval` when vector query behavior changes

## Handoff

Hand off to the Ingestion Agent and Retrieval Agent when provider behavior affects stored or queried vectors.
Bring in the Code Refactor Agent if provider logic leaks into service or CLI modules.
