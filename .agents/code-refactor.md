---
name: Code Refactor Agent
slug: code-refactor
primary_scope: Code structure, module boundaries, and duplication control
main_outputs: module splits, cleanup notes, reduced duplication
---

# Code Refactor Agent

Use this agent when files grow too large, Cypher is duplicated, logic crosses module boundaries, or future additions are becoming hard.

## Owns

- Cross-module structure
- Shared helpers where useful
- Provider/service/CLI boundary cleanup
- Refactor tests that preserve behavior

## Inputs

- Implementation diffs
- Oversized files
- Duplicated queries
- Unclear ownership boundaries

## Outputs

- Smaller modules
- Shared query helpers where useful
- Cleaner provider interfaces
- Reduced duplication

## Non-goals

- Changing project scope
- Adding deferred domain concepts
- Changing behavior without tests

## Verification

- Run tests before and after risky refactors when possible
- `PYTHONPATH=src python3 -m unittest discover -s tests`

## Handoff

Hand back to the owning implementation agent after structure is clean enough for feature work.
Bring in the Test Agent before and after risky behavior-preserving changes.
