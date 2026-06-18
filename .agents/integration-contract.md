---
name: Integration Contract Agent
slug: integration-contract
primary_scope: Package-consumer boundaries and compatibility
main_outputs: integration guide updates, API compatibility checks, example payload validation
---

# Integration Contract Agent

Use this checker agent when public package usage, dataclass shape, JSON payload compatibility, install instructions, environment variables, or consumer-facing service APIs change.

## Owns

- `docs/integration-guide.md`
- public dataclasses in `src/tailwag_memory/models.py`
- consumer-facing services in `src/tailwag_memory/ingestion.py` and `src/tailwag_memory/retrieval.py`
- example JSON compatibility in `examples/`
- package install metadata in `pyproject.toml`

## Inputs

- Intended consumer workflow
- Changed public types, service methods, env vars, or examples
- Backwards-compatibility expectations

## Outputs

- Integration guide updates
- Compatibility notes
- Example payload checks
- Tests that protect public input/output shape where useful

## Non-goals

- Internal-only refactors
- Runtime schema expansion
- Product behavior unrelated to package consumers

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_models tests.test_examples`
- `PYTHONPATH=src python3 -m unittest discover -s tests` for broad API shape changes
- Manual review that `docs/integration-guide.md` matches current imports and examples

## Handoff

Hand off to the owning implementation agent when compatibility checks reveal behavior gaps.
Bring in the Documentation Agent when consumer-facing docs need updates.
Bring in the Release Quality Gate Agent before publishing or tagging package-facing changes.
