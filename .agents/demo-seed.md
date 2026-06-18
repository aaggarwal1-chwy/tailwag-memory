---
name: Demo Seed Agent
slug: demo-seed
primary_scope: Local demo data and reset workflow
main_outputs: seed script, sample payloads, reset instructions
---

# Demo Seed Agent

Use this agent when sample data, repeatable local state, or demo reset behavior changes.

## Owns

- `src/tailwag_memory/demo.py`
- `scripts/seed_demo.py`
- demo payloads in `examples/`
- demo instructions in docs

## Inputs

- Sample people
- Sample places
- Sample episodes
- Sample events

## Outputs

- Seed script
- Sample payload files
- Reset and demo instructions

## Non-goals

- Production ingestion pipeline
- Large synthetic datasets

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_examples`
- `PYTHONPATH=src python3 -m unittest tests.test_ingestion` when seed payloads exercise write behavior

## Handoff

Hand off to the Ingestion Agent when demo data exposes missing write behavior.
Hand off to the Documentation Agent when user-facing demo steps change.
Bring in the Test Agent if examples should become reusable fixtures.
