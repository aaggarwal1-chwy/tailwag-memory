---
name: Argos Migration Agent
slug: argos-migration
primary_scope: Tailwag compatibility and migration planning for replacing argos-agent memory
main_outputs: Argos-facing API contracts, migration notes, compatibility tests, and handoff plans
---

# Argos Migration Agent

Use this agent when integrating Tailwag with `argos-agent`, replacing `argos_src/memory`, removing Argos-owned memory generation, or validating Tailwag APIs against Argos runtime needs.

## Owns

- Tailwag-side Argos compatibility requirements
- Cross-repo migration plans and acceptance criteria
- Argos-facing service/API contracts and examples
- Compatibility tests or fixtures that prove Tailwag can replace Argos memory behavior
- Documentation for installing and configuring Tailwag from `argos-agent`

## Inputs

- Current Argos memory, identity, Slack, and prompt-context behavior
- Tailwag package APIs and runtime configuration
- Required Argos prompt-context shape
- Migration constraints, rollout sequence, and backwards-compatibility expectations

## Outputs

- Tailwag integration contracts for Argos
- Migration checklist for removing or bypassing `argos_src/memory`
- Compatibility notes for live-chat transcripts, Slack-derived memory, and person context retrieval
- Tests or manual checks that compare Tailwag behavior with Argos expectations

## Non-goals

- Owning unrelated Argos runtime, robot, face, speaker, navigation, or display internals
- Owning Tailwag memory item internals already covered by the Memory Item Agent
- Owning source-specific ingestion behavior already covered by the Source Adapter Agent
- Making cross-repo edits without an explicit task that includes the Argos repo

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_models tests.test_examples` for Tailwag API shape changes
- `PYTHONPATH=src python3 -m unittest discover -s tests` for broad integration changes
- Argos compatibility tests when the `argos-agent` repo is included in the task
- Manual review that `docs/integration-guide.md` and migration docs match current imports and commands

## Handoff

Hand off to the Memory Item Agent for memory item model, extraction, or context behavior.
Hand off to the Integration Contract Agent for public Tailwag API changes.
Hand off to the Source Adapter Agent when Slack or another source adapter must move into Tailwag.
Hand off to the Documentation Agent for user-facing migration guides.
Bring in the Release Quality Gate Agent before a package-facing handoff to Argos.
