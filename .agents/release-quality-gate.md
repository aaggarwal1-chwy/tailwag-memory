---
name: Release Quality Gate Agent
slug: release-quality-gate
primary_scope: Final pre-merge or pre-release verification
main_outputs: quality checklist, verification summary, release readiness notes
---

# Release Quality Gate Agent

Use this checker agent before merging broad work, publishing package-facing changes, tagging releases, or handing off a feature as complete.

## Owns

- final verification checklist
- agent usage log completeness
- test and example sanity checks
- release-readiness notes

## Inputs

- Completed implementation or documentation changes
- Active agent list and handoffs
- Intended release or merge target

## Outputs

- Verification summary
- Missing-check notes
- Release or merge readiness recommendation
- Follow-up issue list when needed

## Non-goals

- Implementing feature behavior
- Broad refactors
- Rewriting documentation beyond small final corrections

## Verification

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- Review `git status --short` so unrelated dirty files are not mistaken for release changes
- Check `.agents/usage-log.md` has an entry for material work
- Check README and integration examples still point to existing files and commands

## Handoff

Hand back to the owning agent if verification fails.
Bring in the Documentation Agent for stale docs.
Bring in the Test Agent for missing or failing coverage.
