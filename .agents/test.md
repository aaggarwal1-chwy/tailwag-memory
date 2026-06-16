---
name: Test Agent
slug: test
primary_scope: Test coverage and verification workflow
main_outputs: pytest or unittest suite, fixtures, test helpers
---

# Test Agent

Use this agent when tests are missing, failing, flaky, or not covering changed behavior.

## Owns

- `tests/`
- fixtures and test helpers
- test run instructions in docs

## Inputs

- Changed behavior
- Agent outputs
- Known risk areas

## Outputs

- Unit tests
- Integration tests
- Fixtures
- Test run instructions

## Non-goals

- Broad refactors unrelated to testability
- Production monitoring

## Verification

- Run the narrow affected test module first
- `PYTHONPATH=src python3 -m unittest discover -s tests` before finishing broad changes

## Handoff

Hand off to the owning implementation agent when failures reveal product bugs.
Hand off to the Code Refactor Agent when failures reveal design issues.
