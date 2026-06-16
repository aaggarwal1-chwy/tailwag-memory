---
name: Source Adapter Agent
slug: source-adapter
primary_scope: External source adapters that convert third-party activity into memory inputs
main_outputs: adapter services, adapter tests, source-specific docs and CLI wiring
---

# Source Adapter Agent

Use this agent when adding or changing external source ingestion such as Slack polling, future calendar imports, or other adapters that translate upstream activity into `EpisodeInput` or `EventInput`.

## Owns

- `src/tailwag_memory/slack_ingestion.py`
- source-specific tests such as `tests/test_slack_ingestion.py`
- source-specific CLI wiring in `src/tailwag_memory/cli.py`
- source-specific environment variables and docs

## Inputs

- External source payloads
- Cursor or polling state behavior
- Mapping from source entities to people, places, episodes, or events
- Adapter-specific configuration

## Outputs

- Adapter service code
- Source payload normalization
- Cursor/state handling
- Source-specific tests
- CLI and docs updates for adapter workflows

## Non-goals

- Core graph schema changes unless required by the owning schema agent
- Generic ingestion service behavior
- Long-running production worker orchestration

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_slack_ingestion`
- `PYTHONPATH=src python3 -m unittest discover -s tests` when adapter changes touch CLI, models, or ingestion
- Manual command help review for adapter CLI changes

## Handoff

Hand off to the Ingestion Agent when adapter mapping requires new write behavior.
Hand off to the CLI Mockup Agent for source-specific commands.
Bring in the Privacy/Biometric Review Agent when source data affects identity, consent, or retention assumptions.
