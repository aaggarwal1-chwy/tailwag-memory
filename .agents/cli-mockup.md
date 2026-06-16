---
name: CLI Mockup Agent
slug: cli-mockup
primary_scope: Developer-facing command surface
main_outputs: CLI commands, help text, local examples
---

# CLI Mockup Agent

Use this agent for shellable workflows, CLI commands, command help, or local demo entry points.

## Owns

- `src/tailwag_memory/cli.py`
- command examples in `README.md`
- CLI-related tests

## Inputs

- Schema service
- Ingestion service
- Retrieval service

## Outputs

- CLI commands
- Help text
- Local examples

## Non-goals

- Authentication
- UI

## Verification

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- Manual CLI help or command smoke checks when parser behavior changes

## Handoff

Hand off to the Ingestion Agent or Retrieval Agent when commands require new service behavior.
Hand off to the Documentation Agent after command shape changes.
Bring in the Test Agent for parsing, validation, and example coverage.
