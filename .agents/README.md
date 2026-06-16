# Agent Router

Use these files as concrete role cards for the agents listed in `docs/agent-trigger-matrix.md`.
They are repo-local instructions for Codex or human contributors, not runtime application services.

## Required Workflow

1. Select one primary agent before changing files.
2. Add supporting agents only when their scope is directly touched.
3. If a platform subagent is spawned, tell it which named agent role to follow.
4. Keep agent write scopes separate during parallel work.
5. Update `.agents/usage-log.md` before finishing the task.

## Agent Files

| Agent | File | Use When |
| --- | --- | --- |
| Project Scaffold Agent | `project-scaffold.md` | Repo structure, package metadata, Docker, env examples, folders |
| Neo4j Schema Agent | `neo4j-schema.md` | Constraints, labels, vector indexes, schema init |
| Mock OpenAI Embeddings Agent | `mock-openai-embeddings.md` | Embedding provider interface or deterministic mock vectors |
| Ingestion Agent | `ingestion.md` | Episode/event write paths, people/place upserts, relationships |
| Retrieval Agent | `retrieval.md` | Graph lookups, vector reads, hybrid search, biometric search |
| Demo Seed Agent | `demo-seed.md` | Sample payloads, seed/reset workflows, repeatable demo data |
| CLI Mockup Agent | `cli-mockup.md` | CLI commands, help text, local entry points |
| Source Adapter Agent | `source-adapter.md` | External source adapters such as Slack polling |
| Integration Contract Agent | `integration-contract.md` | Package-consumer APIs, examples, env vars, install workflow |
| Privacy/Biometric Review Agent | `privacy-biometric-review.md` | Consent, biometric vectors, retention, raw media boundaries |
| Scope Guard Agent | `scope-guard.md` | Deferred concept and scope boundary checks |
| Release Quality Gate Agent | `release-quality-gate.md` | Final pre-merge or pre-release verification |
| Test Agent | `test.md` | Tests, fixtures, verification workflow |
| Code Refactor Agent | `code-refactor.md` | Module boundaries, duplication, code organization |
| Documentation Agent | `documentation.md` | README, architecture docs, examples, scope notes |

## Handoff Defaults

- Schema before ingestion when graph shape changes.
- Ingestion before retrieval when write behavior creates new read behavior.
- Implementation before CLI when commands wrap existing services.
- Source adapters before ingestion when external payloads need normalization.
- Privacy review when changes touch consent, biometrics, retention, or raw media boundaries.
- Scope guard when changes approach deferred concepts or out-of-scope storage systems.
- Integration contract review when public package usage changes.
- Tests before broadening a difficult or risky feature.
- Documentation after user-facing behavior, command shape, or scope changes.
- Release quality gate before broad merges, package-facing releases, or final handoff.
