# Argos Post-Migration Compatibility Note

## Purpose

Current Argos integration lives in `argos_src/memory_provider/`, especially:

- `argos_src/memory_provider/tailwag.py`
- `argos_src/memory_provider/slack.py`
- `docs/memory_provider.md`
- `docs/slack_memory.md`

Tailwag remains the source of truth for durable social/context memory. Argos
remains the source of truth for realtime runtime behavior, robot identity,
face/speaker recognition, raw media handling, and final prompt assembly.

## Current Boundary

Tailwag owns:

- Neo4j-backed durable memory storage
- episode and event ingestion
- transcript-derived memory extraction
- per-person memory consolidation
- graph and vector retrieval
- deterministic/vector-derived person context
- Slack polling as a Tailwag source adapter

Argos owns:

- realtime turn ownership
- robot/runtime identity
- face and speaker recognition
- raw audio, video, and transcript production
- profile and directory configuration
- final prompt assembly
- Tailwag provider wiring and operator rollout

Argos currently keeps biometric vectors local. Tailwag still supports optional
caller-supplied `Person.face_embedding` and `Person.audio_embedding`, but the
current Argos provider sends non-biometric person metadata for encounter and
identity updates.

## Live Argos Contracts

Argos relies on these Tailwag package surfaces:

- `TailwagMemoryClient.from_env()`
- `TailwagMemoryClient.person_context(person_id, current_text=...)`
- `TailwagMemoryClient.record_episode(episode, extract_memory=...)`
- `TailwagMemoryClient.search_semantic_memory(...)`
- `TailwagMemoryClient.upsert_person(PersonInput(...))`
- `TailwagMemoryClient.archive_person(person_id)`
- `TailwagMemoryClient.rekey_person_by_email(email, new_person_id)`
- `tailwag_memory.slack_ingestion.SlackWebApiClient`
- `tailwag_memory.slack_ingestion.SlackMemoryPoller`

Argos treats `person_context()` as prompt-ready text and maps it into existing
prompt fields such as `About`, `Potential Followups`, and preferred language.
If Tailwag changes the rendered context format, Argos provider tests should be
updated with the Tailwag change.

Argos records live conversation memory as normal Tailwag `EpisodeInput` records
with `episode_type="conversation"`, `source="live_chat"` participants, and
caller-owned `person_id` values. Argos treats `EpisodeRecordResult` as
Tailwag-owned and should not depend on generated memory item IDs.

Argos semantic memory tools call `search_semantic_memory(...)` and expect
separate `episodes` and `memory_items` lists.

## Slack And Identity

Slack ingestion is Tailwag-backed. Argos can schedule polling, but Tailwag owns
Slack episode construction, transcript formatting, memory extraction, and
persistence.

Slack users may start as temporary `Person.id="slack:<user_id>"` records. When a
consuming system later confirms a canonical identity by email, it can call
`rekey_person_by_email(email, new_person_id)` to converge that Slack-created
person to a caller-owned canonical ID. Rekeying changes the `Person.id` in place
so existing episodes, events, mentions, and memory items stay attached to the
same graph node.

`TailwagMemoryClient.canonical_person_id_by_email(email)` is package-level
resolver support for Slack polling and other adapters that need to map a
normalized email to one active caller-owned canonical person. Argos does not
call this method directly in the live runtime; package-level `SlackMemoryPoller`
uses it automatically only when its `episode_recorder` exposes the method and no
explicit resolver is supplied.

`MemoryItem.id` values are opaque and are not renamed during person rekeying.
Consumers should use person-scoped APIs and graph relationships after rekey
rather than parsing memory IDs.

## Compatibility Checks

Before package-facing changes that could affect Argos, run Tailwag API smoke
checks when practical:

```bash
PYTHONPATH=src python3 -m unittest tests.test_models tests.test_examples
PYTHONPATH=src python3 -m unittest discover -s tests
tailwag schema init --help
tailwag episode create --help
tailwag memory extract --help
tailwag memory consolidate --help
tailwag slack poll --help
```

When the Argos repo is included in the task, also run or request the Argos
memory provider tests that cover prompt context mapping, live episode recording,
encounter updates, Slack polling, and factory wiring.
