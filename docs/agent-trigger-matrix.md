# Agent And Subagent Trigger Matrix

## Purpose

This document defines the project agents and subagents for the Neo4j-only memory project. These are project-scoped Codex custom agents plus planning boundaries for human implementation work. They are not application runtime services.

Each agent owns a clear scope, trigger conditions, expected outputs, and handoff points. The goal is to prevent broad, tangled implementation passes.

Concrete repo-local custom agents and their usage log live in `.codex/agents/`, and the root `AGENTS.md` makes agent selection part of the repository workflow. Use this matrix to decide which custom agent applies, then record material work in `.codex/agents/usage-log.md`.

## Agent Roster

| Agent | Primary Scope | Main Outputs |
| --- | --- | --- |
| Project Scaffold Agent | Repo structure and local developer workflow | package files, Docker Compose, `.env.example`, folders |
| Neo4j Schema Agent | Database schema, constraints, vector indexes | idempotent schema setup code |
| OpenAI Embeddings Agent | Embedding interface, OpenAI runtime provider, and deterministic mock provider | provider interface, OpenAI embeddings, mock vectors, embedding tests |
| Ingestion Agent | Episode and event write paths | ingestion services, Cypher writes, ingestion tests |
| Memory Item Agent | Durable transcript-derived memory item semantics and behavior | memory item models, services, extraction contracts, context formatting, tests |
| Retrieval Agent | Graph and vector read paths | retrieval services, hybrid search, retrieval tests |
| Demo Seed Agent | Local demo data and reset workflow | seed script, sample episode payloads |
| CLI Mockup Agent | Developer-facing command surface | CLI commands, command docs |
| Source Adapter Agent | External source adapters that convert third-party activity into memory inputs | adapter services, adapter tests, source-specific docs and CLI wiring |
| Integration Contract Agent | Package-consumer boundaries and compatibility | integration guide updates, API compatibility checks, example payload validation |
| Argos Migration Agent | Tailwag compatibility and migration planning for replacing argos-agent memory | Argos-facing API contracts, migration notes, compatibility tests, handoff plans |
| Privacy/Biometric Review Agent | Consent, biometric vectors, retention language, and raw media boundaries | privacy review notes, consent/biometric docs, guardrail tests |
| Scope Guard Agent | Scope boundary checks and deferred concept protection | scope review notes, deferred-concept checks, scope documentation updates |
| Release Quality Gate Agent | Final pre-merge or pre-release verification | quality checklist, verification summary, release readiness notes |
| Test Agent | Test coverage and verification workflow | pytest suite, fixtures, test helpers |
| Code Refactor Agent | Code structure, module boundaries, duplication control | refactor PRs/patches, module splits, cleanup notes |
| Documentation Agent | User-facing and contributor-facing docs | README updates, architecture notes, examples |

## Trigger Matrix

| Trigger | Agent | Subagents To Consider | Scope Boundary | Handoff |
| --- | --- | --- | --- | --- |
| Repo lacks package structure, local run instructions, or environment examples | Project Scaffold Agent | Documentation Agent | Create scaffolding only; do not implement domain logic | Handoff to Schema Agent and CLI Mockup Agent |
| Need Neo4j constraints, labels, indexes, or schema migration changes | Neo4j Schema Agent | Test Agent | Only `Person`, `Episode`, `Event`, `Place`, `MemoryItem`, `PARTICIPATED_IN`, `OCCURRED_AT`, `ATTENDED`, `HAS_MEMORY`, `SUPPORTED_BY`, `ADDRESSED_BY`, `SUPERSEDED_BY`, episode transcript vector index, person biometric vector indexes, and the `MemoryItem.summary_embedding` vector index | Handoff to Ingestion Agent once schema is available |
| Need embedding generation or embedding configuration | OpenAI Embeddings Agent | Test Agent, Code Refactor Agent | Runtime embeddings use OpenAI; tests use deterministic mocks and no network calls | Handoff to Ingestion Agent and Retrieval Agent |
| Need to create or update episode memory records or place events | Ingestion Agent | Neo4j Schema Agent, OpenAI Embeddings Agent, Test Agent | Write path only; no retrieval ranking logic | Handoff to Retrieval Agent for query behavior |
| Need durable transcript-derived memory items, memory item extraction, memory item context formatting, or memory item vector retrieval | Memory Item Agent | Neo4j Schema Agent, OpenAI Embeddings Agent, Retrieval Agent, Integration Contract Agent, Test Agent, Scope Guard Agent | Memory item semantics only; do not expand into a broad ontology, triple store, or open-ended semantic fact graph | Handoff to Retrieval Agent for context selection and Integration Contract Agent for public APIs |
| Need person participation lookup, place lookup, event lookup, episode vector search, person face recognition, person audio recognition, or hybrid search | Retrieval Agent | OpenAI Embeddings Agent, Test Agent | Read path only; no schema expansion beyond approved scope | Handoff to CLI Mockup Agent for commands |
| Need sample local data or repeatable demo state | Demo Seed Agent | Ingestion Agent, Documentation Agent | Demo records only; no production import pipeline | Handoff to Test Agent for fixture reuse |
| Need a developer command, shellable workflow, or local demo entry point | CLI Mockup Agent | Ingestion Agent, Retrieval Agent, Source Adapter Agent, Documentation Agent | CLI-first; no API surface | Handoff to Documentation Agent for usage docs |
| Need to ingest Slack or another external source into `EpisodeInput` or `EventInput` | Source Adapter Agent | Ingestion Agent, CLI Mockup Agent, Privacy/Biometric Review Agent, Test Agent | Adapter and mapping behavior only; core writes stay in ingestion services | Handoff to Ingestion Agent for write behavior |
| Public dataclasses, service methods, env vars, package metadata, examples, or integration docs change | Integration Contract Agent | Documentation Agent, Test Agent, Release Quality Gate Agent | Package-consumer boundaries only; no internal refactor unless needed to preserve compatibility | Handoff to owning implementation agent for behavior gaps |
| Need to replace or integrate with `argos-agent`, remove `argos_src/memory`, or validate Argos-facing Tailwag APIs | Argos Migration Agent | Integration Contract Agent, Memory Item Agent, Source Adapter Agent, Documentation Agent, Test Agent, Release Quality Gate Agent | Tailwag compatibility and migration planning only; no unrelated Argos runtime, robot, face, speaker, navigation, or display internals | Handoff to Memory Item Agent for Tailwag memory behavior and Source Adapter Agent for moved Slack ingestion |
| Consent, `face_embedding`, `audio_embedding`, retention, recognition source, Slack identity, or raw media language changes | Privacy/Biometric Review Agent | Ingestion Agent, Retrieval Agent, Documentation Agent, Scope Guard Agent | Review and guardrails only; no upstream recognition implementation | Handoff to owning implementation agent for behavior fixes |
| A change risks adding deferred concepts, confidence fields, `org_id`, secondary persistence, or external vector databases | Scope Guard Agent | Neo4j Schema Agent, Ingestion Agent, Memory Item Agent, Documentation Agent, Test Agent | Scope review and guardrails only unless scope is explicitly updated; approved `MemoryItem` work is limited to durable transcript-derived memory, not a broad ontology | Handoff to Documentation Agent when scope changes |
| Broad work is ready for final handoff, merge, package-facing release, or tag | Release Quality Gate Agent | Test Agent, Documentation Agent, Integration Contract Agent | Final verification only; do not implement feature behavior | Handoff back to owning agent if verification fails |
| Tests are missing, failing, flaky, or not covering changed behavior | Test Agent | Any implementation agent related to the failing area | Tests and fixtures only unless fixing a small test-discovered bug | Handoff to Code Refactor Agent if failures reveal design issues |
| A file grows too large, Cypher is duplicated, logic crosses module boundaries, or future additions look hard | Code Refactor Agent | Test Agent, Documentation Agent | Structural cleanup only; no new product behavior unless needed to preserve current behavior | Handoff back to owning implementation agent |
| README, architecture docs, command examples, or scope notes are stale | Documentation Agent | Any owning implementation agent | Docs only; do not modify behavior | Handoff to Test Agent if docs expose missing verification |

## Subagent Definitions

### Project Scaffold Agent

Owns the initial local project shape.

Inputs:

- desired stack
- repo state
- local development assumptions

Outputs:

- `pyproject.toml`
- `docker-compose.yml`
- `.env.example`
- package directories
- test directories

Non-goals:

- Cypher implementation
- ingestion behavior
- retrieval behavior

### Neo4j Schema Agent

Owns graph schema setup.

Inputs:

- approved graph model
- vector dimension configuration

Outputs:

- constraints for `Person.id`, `Episode.id`, `Event.id`, `MemoryItem.id`, and `(Place.building_code, Place.room_id)`
- vector indexes for `Episode.transcript_embedding`, `Person.face_embedding`, `Person.audio_embedding`, and `MemoryItem.summary_embedding`
- schema initialization command support

Non-goals:

- adding deferred labels
- adding confidence fields
- adding `org_id`

### OpenAI Embeddings Agent

Owns embedding provider boundaries.

Inputs:

- text to embed
- configured vector dimension

Outputs:

- OpenAI-backed production embeddings
- deterministic fake embeddings for tests
- provider interface
- tests proving stable dimensions and deterministic outputs

Non-goals:

- choosing a production model
- adding non-episode embedding targets

### Ingestion Agent

Owns the write path.

Inputs:

- caller-provided `Episode.id`
- caller-provided `Event.id`
- caller-provided `Person.id`
- participant roles and relationship provenance sources
- optional caller-supplied face embeddings
- optional caller-supplied audio embeddings
- episode transcript
- event description and start/end times
- `building_code`
- `room_id`

Outputs:

- persisted episode
- persisted event
- upserted people
- updated `Person.last_seen`
- stored `Person.face_embedding` when supplied
- stored `Person.audio_embedding` when supplied
- upserted place
- graph relationships
- episode embeddings

Non-goals:

- semantic fact extraction
- utterance segmentation
- object/activity detection
- retrieval ranking

### Memory Item Agent

Owns durable transcript-derived memory item semantics and behavior.

Inputs:

- transcript or episode evidence that can support durable person memory
- approved memory item kinds and lifecycle rules
- existing person, episode, embedding, and retrieval contracts
- Argos-facing prompt context requirements when applicable

Outputs:

- memory item models and services
- create, support, address, supersede, merge, and retrieval behavior for memory items
- evidence links such as `(:Person)-[:HAS_MEMORY]->(:MemoryItem)`, `(:MemoryItem)-[:SUPPORTED_BY]->(:Episode)`, follow-up resolution links such as `(:MemoryItem)-[:ADDRESSED_BY]->(:Episode)`, and supersession links such as `(:MemoryItem)-[:SUPERSEDED_BY]->(:MemoryItem)`
- tests for memory item validation, dedupe, lifecycle, extraction, and context formatting

Non-goals:

- owning all schema work when a focused Neo4j schema change is required
- owning embedding provider internals
- owning source-specific polling such as Slack API access
- owning Argos repo migration code
- implementing a broad ontology, triple store, or open-ended semantic fact graph

### Retrieval Agent

Owns the read path.

Inputs:

- natural language query text
- face embedding vector
- audio embedding vector
- optional `person_id`
- optional `building_code`
- optional `room_id`
- optional retrieval limit

Outputs:

- matching episode IDs
- matching event IDs for place event queries
- matching person IDs for biometric queries
- transcript snippets
- vector scores where applicable

Non-goals:

- writes
- data import
- semantic consolidation

### Demo Seed Agent

Owns repeatable mock data.

Inputs:

- sample people
- sample places
- sample episodes
- sample events

Outputs:

- seed script
- sample payload files
- reset/demo instructions

Non-goals:

- production ingestion pipeline
- large synthetic datasets

### CLI Mockup Agent

Owns the developer interaction surface.

Inputs:

- schema service
- ingestion service
- retrieval service

Outputs:

- CLI commands
- help text
- local examples

Non-goals:

- authentication
- UI

### Source Adapter Agent

Owns external source adapters that translate upstream activity into memory inputs.

Inputs:

- external source payloads
- cursor or polling state behavior
- mapping from source entities to people, places, episodes, or events
- adapter-specific configuration

Outputs:

- adapter service code
- source payload normalization
- cursor/state handling
- source-specific tests
- CLI and docs updates for adapter workflows

Non-goals:

- core graph schema changes unless required by the owning schema agent
- generic ingestion service behavior
- long-running production worker orchestration

### Integration Contract Agent

Owns package-consumer boundaries and compatibility.

Inputs:

- intended consumer workflow
- changed public types, service methods, env vars, or examples
- compatibility expectations when the task explicitly states them

Outputs:

- integration guide updates
- compatibility notes
- example payload checks
- tests that protect public input/output shape where useful

Non-goals:

- internal-only refactors
- runtime schema expansion
- product behavior unrelated to package consumers

### Argos Migration Agent

Owns Tailwag compatibility and migration planning for replacing `argos-agent` memory.

Inputs:

- current Argos memory, identity, Slack, and prompt-context behavior
- Tailwag package APIs and runtime configuration
- required Argos prompt-context shape
- migration constraints, rollout sequence, and explicitly stated compatibility expectations

Outputs:

- Tailwag integration contracts for Argos
- migration checklist for removing or bypassing `argos_src/memory`
- compatibility notes for live-chat transcripts, Slack-derived memory, and person context retrieval
- tests or manual checks that compare Tailwag behavior with Argos expectations

Non-goals:

- owning unrelated Argos runtime, robot, face, speaker, navigation, or display internals
- owning Tailwag memory item internals already covered by the Memory Item Agent
- owning source-specific ingestion behavior already covered by the Source Adapter Agent
- making cross-repo edits without an explicit task that includes the Argos repo

### Privacy/Biometric Review Agent

Owns review of consent, biometric vectors, retention language, and raw media boundaries.

Inputs:

- changed biometric or identity-related behavior
- consent and retention assumptions
- data source and provenance details

Outputs:

- review notes on consent and biometric handling
- documentation updates for privacy boundaries
- tests that preserve "vectors only, no raw media" behavior where practical

Non-goals:

- legal advice
- production policy design
- implementing upstream face, audio, or identity recognition

### Scope Guard Agent

Owns scope boundary checks and deferred concept protection.

Inputs:

- proposed schema, model, ingestion, retrieval, or adapter changes
- deferred concept list
- current scope

Outputs:

- scope review notes
- documentation updates when scope intentionally changes
- guardrail tests for excluded labels, fields, or storage systems

Non-goals:

- implementing feature behavior
- blocking intentional scope changes after docs are updated
- replacing the owning implementation agent

### Release Quality Gate Agent

Owns final pre-merge or pre-release verification.

Inputs:

- completed implementation or documentation changes
- active agent list and handoffs
- intended release or merge target

Outputs:

- verification summary
- missing-check notes
- release or merge readiness recommendation
- follow-up issue list when needed

Non-goals:

- implementing feature behavior
- broad refactors
- rewriting documentation beyond small final corrections

### Test Agent

Owns verification.

Inputs:

- changed behavior
- agent outputs

Outputs:

- unit tests
- integration tests
- fixtures
- test run instructions

Non-goals:

- broad refactors unrelated to testability
- production monitoring

### Code Refactor Agent

Owns code health and modularity.

Inputs:

- implementation diffs
- oversized files
- duplicated queries
- unclear ownership boundaries

Outputs:

- smaller modules
- shared query helpers where useful
- cleaner provider interfaces
- reduced duplication

Non-goals:

- changing project scope
- adding deferred domain concepts
- changing behavior without tests

### Documentation Agent

Owns project documentation.

Inputs:

- implemented features
- intended workflow
- known limitations

Outputs:

- README updates
- architecture notes
- command examples
- scope notes

Non-goals:

- implementation changes
- schema changes

## Escalation Rules

- If a task touches schema and ingestion, start with the Neo4j Schema Agent, then hand off to the Ingestion Agent.
- If a task touches ingestion and retrieval, keep writes in the Ingestion Agent and reads in the Retrieval Agent.
- If a change adds a new concept beyond `Person`, `Episode`, `Event`, `Place`, or approved transcript-derived `MemoryItem`, pause and update the project scope before implementation.
- If a change adds or changes memory item semantics, trigger the Memory Item Agent before handing off to schema, embeddings, or retrieval owners.
- If a change targets `argos-agent` compatibility or replacement of `argos_src/memory`, trigger the Argos Migration Agent.
- If code starts mixing provider logic, Cypher, CLI parsing, and domain models in one file, trigger the Code Refactor Agent.
- If a feature is difficult to test, trigger the Test Agent before expanding the feature.
- If a change touches external source polling or source-to-memory mapping, trigger the Source Adapter Agent.
- If a change touches package-consumer usage, trigger the Integration Contract Agent.
- If a change touches Argos-facing package usage, trigger the Argos Migration Agent and Integration Contract Agent.
- If a change touches consent, biometrics, retention, recognition provenance, or raw media boundaries, trigger the Privacy/Biometric Review Agent.
- If a change risks deferred concepts or out-of-scope storage, trigger the Scope Guard Agent.
- Before broad handoff, merge, package-facing release, or tag, trigger the Release Quality Gate Agent.

## Deferred Concept Parking Lot

These concepts are intentionally not implemented now but should remain easy to add later:

- `Robot`
- `ObjectConcept`
- `Activity`
- `Utterance`
- `SemanticFact`

Durable transcript-derived `MemoryItem` work is the approved narrow path for person memory extraction. It should not be treated as permission to implement a broad `SemanticFact` ontology or triple store.

When one of these becomes active, create or update:

- schema section
- model definitions
- ingestion ownership
- retrieval ownership
- tests
- documentation
