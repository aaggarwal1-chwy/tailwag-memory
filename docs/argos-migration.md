# Argos Migration Guide

## Purpose

This guide describes the Tailwag-side plan for replacing or bypassing `argos-agent/argos_src/memory`. Tailwag should be treated as the durable memory engine and Python package. Argos should keep ownership of realtime turn handling, robot/runtime identity, face and speaker recognition, transcription, profile configuration, and prompt assembly.

Tailwag is not a drop-in `argos_src.memory` module. The migration should use a small Argos compatibility adapter that preserves Argos-facing call sites while delegating persistence, retrieval, extraction, and consolidation to Tailwag.

For Tailwag API details, see [Memory Endpoints Reference](memory-endpoints.md). For general package usage, see [Python Package Integration Guide](integration-guide.md). For the current graph model and scope boundaries, see [Architecture](architecture.md).

## Ownership Boundary

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
- operator rollout and compatibility adapter wiring

## Required Compatibility Adapter

Argos should construct an adapter where it currently constructs memory runtime objects. The adapter can preserve old Argos-facing exports or equivalent call sites while delegating to Tailwag.

Expected adapter responsibilities:

- `MemoryStore`: backed by Tailwag services instead of SQLite. It should cover `upsert_item`, `update_item`, `archive_item`, `merge_items`, `get_item`, `list_items`, `list_active_items`, plus compatibility methods such as `record_encounter` and `list_recent_encounters` if Argos still calls them.
- `MemoryContextCompiler`: backed by Tailwag `person_context()` and retrieval. It should preserve the prompt fields Argos expects, such as profile lines, follow-up lines, preferred language, and site memory blocks.
- `PreferenceExtractor`: convert completed Argos live-chat segments into `EpisodeInput` records and call `TailwagMemoryClient.record_episode(..., extract_memory=True)`.
- `SlackMemoryService`: either wrap Tailwag Slack polling or keep Argos scheduling while recording Slack activity as Tailwag episodes.

The old `memory_store.db_path` setting should become deprecated or ignored in Tailwag mode. Neo4j, OpenAI, and Slack configuration should come from Tailwag settings or the process environment.

## Runtime Mapping

On Argos startup:

- Load Tailwag configuration.
- Construct the Argos compatibility adapter.
- Run schema initialization through an operator/admin path, not repeatedly during every realtime turn.
- Keep SQLite memory writes disabled or read-only during a staged cutover.

On each realtime turn:

- Use the adapter compiler to populate Argos prompt fields.
- Call Tailwag `person_context(person_id, current_text=...)` when Argos has an identified person.
- Keep final prompt assembly in Argos.

After completed attributed live-chat turns:

- Buffer the turn or segment in Argos.
- Convert it to one Tailwag `EpisodeInput`.
- Call `TailwagMemoryClient.record_episode(..., extract_memory=True)`.
- Let Tailwag create, update, archive, or merge durable person memory items.

For face or speaker recognition:

- Argos decides the canonical `Person.id`.
- Argos supplies face/audio embeddings only after consent and enrollment decisions.
- Tailwag stores supplied vectors and excludes archived or non-consented people from recognition.
- Encounter-only behavior should become either a short encounter episode or an adapter-level compatibility record backed by Tailwag data.

For Slack memory:

- Prefer Tailwag Slack polling so Slack threads become normal Tailwag episodes.
- If Argos keeps its own background service controls, that service should call Tailwag polling/recording rather than writing SQLite memory operations.

## Person Identity

Argos should pass canonical person IDs that match Tailwag's current canonical Slack resolution convention: `person_*`.

Enroll or refresh a known person profile:

```python
from tailwag_memory import PersonInput, TailwagMemoryClient

person = PersonInput(
    id="person_jamie",
    display_name="Jamie",
    email="jamie@example.com",
    consent_status="consented",
    face_embedding=[0.01] * 64,
    audio_embedding=[0.02] * 64,
)

with TailwagMemoryClient.from_env() as memory:
    person_id = memory.upsert_person(person)
```

Later identity refreshes can send only the fields Argos wants to change. Omitted fields preserve existing Tailwag values:

```python
with TailwagMemoryClient.from_env() as memory:
    memory.upsert_person(
        PersonInput(
            id="person_jamie",
            display_name="Jamie A.",
        )
    )
```

When Slack has already created a person such as `slack:U0123456789`, Argos can converge that node to a canonical person ID after it confirms a unique shared email identity:

```python
with TailwagMemoryClient.from_env() as memory:
    rekeyed = memory.rekey_person_by_email(
        email="jamie@example.com",
        new_person_id="person_jamie",
    )
```

`rekey_person_by_email()` changes one Slack-owned temporary `Person.id` property in place. Existing Slack episodes, events, and memory items stay attached to the same graph node. Existing `MemoryItem.id` values are not renamed, so Argos should treat memory IDs as opaque stable IDs and use person-scoped Tailwag APIs plus graph relationships after rekey.

The method returns `False` when email does not identify exactly one person, when the matched person is not the target or a Slack-owned temporary person, or when the canonical ID is already used by a different `Person` node. Argos should treat these cases as identity-review work, not auto-merge work.

Archive a person when Argos needs to retire an identity or revoke biometric recognition:

```python
with TailwagMemoryClient.from_env() as memory:
    archived = memory.archive_person("person_jamie")
```

Archived people keep historical graph data, including prior episodes, events, and memory items. Archiving removes stored biometric vectors and excludes the profile from biometric recognition. Archive is not a full retention deletion mechanism; retention and deletion policy remains caller-owned.

## Recording Argos Episodes

New live conversation memory should enter Tailwag as normal episodes through the high-level client:

```python
from tailwag_memory import EpisodeInput, PersonInput, PlaceInput, TailwagMemoryClient

episode = EpisodeInput(
    id="episode_external_001",
    episode_type="conversation",
    start_time="2026-06-16T14:00:00+00:00",
    end_time=None,
    summary="Jamie prefers Spanish and likes hands-on robot demos.",
    transcript="Jamie: I prefer Spanish and like hands-on robot demos.",
    retention_class="standard",
    place=PlaceInput(building_code="MAIN", room_id="101"),
    participants=[
        PersonInput(
            id="person_jamie",
            display_name="Jamie",
            role="speaker",
            source="live_chat",
        )
    ],
)

with TailwagMemoryClient.from_env() as memory:
    result = memory.record_episode(episode)

print(result.episode_id)
print(result.memory_results)
print(result.memory_errors)
```

`record_episode(..., extract_memory=True)` is the default. If Argos wants to store an episode without OpenAI-backed memory extraction, pass `extract_memory=False`.

Backfill or debug extraction for an episode that is already in Neo4j:

```python
with TailwagMemoryClient.from_env() as memory:
    result = memory.extract_memory_for_episode(
        "episode_external_001",
        person_id="person_jamie",
    )
```

High-level episode recording checks every participant. Existing-episode extraction defaults to speaker participants, falling back to all participants when no speaker role is present. Use `person_id=` or `tailwag memory extract --person-id` to narrow debugging.

## Person Context Shape

Argos prompt code should treat Tailwag `person_context()` output as prompt-ready text, not as a structured schema. The context includes durable memory sections, visible follow-ups, and bounded recent episode lines when available.

```python
from tailwag_memory import TailwagMemoryClient

with TailwagMemoryClient.from_env() as memory:
    context = memory.person_context(
        "person_jamie",
        current_text="robot demo later today",
    )
```

If Argos needs old structured prompt fields, the compatibility adapter should parse or map Tailwag context into Argos's expected `profile_lines`, `followup_lines`, `preferred_language`, and site memory blocks. That compatibility shape belongs in the Argos repo unless Tailwag later adopts it as a package contract.

## Memory Consolidation

Episode memory extraction works one episode at a time. For slower background work, Tailwag can consolidate repeated or related per-person episode evidence:

```python
with TailwagMemoryClient.from_env() as memory:
    result = memory.consolidate_memory(person_id="person_jamie")
```

CLI workflow:

```bash
tailwag memory consolidate --person-id person_jamie
tailwag memory consolidate --all --person-limit 100
```

The consolidation pass uses Neo4j episode summary vector search to reduce candidate evidence before calling OpenAI. It stays person-scoped, validates provider-supplied supporting episode IDs, and writes only `MemoryItem`, `SUPPORTED_BY`, and `SUPERSEDED_BY` records. It is not the deferred asynchronous semantic consolidation queue/orchestrator and does not add `SemanticFact`, confidence properties, external vector databases, or new graph labels.

## Migration Checklist

1. Install Tailwag into the Argos environment.
2. Configure Neo4j and OpenAI settings, including `TAILWAG_EMBEDDING_DIMENSION`, `TAILWAG_EMBEDDING_MODEL`, and `TAILWAG_SYNTHESIS_MODEL`.
3. Initialize the Tailwag Neo4j schema through an operator/admin step.
4. Add an Argos compatibility adapter around Tailwag services.
5. Switch live-chat segment recording to Tailwag `record_episode()`.
6. Switch prompt context reads to Tailwag `person_context()` through the adapter.
7. Route Slack memory through Tailwag polling or Tailwag episode recording.
8. Use `person_*` canonical IDs and `rekey_person_by_email()` for Slack-to-Argos identity convergence.
9. Archive rather than delete retired identities when historical memory should remain inspectable.
10. Disable old SQLite writes after parity checks pass.

## Compatibility Tests

Argos-side compatibility tests should cover:

- startup wiring and Tailwag configuration loading
- schema initialization handled outside realtime turn flow
- turn-context prompt output
- preferred-language propagation
- live-chat segment recording through Tailwag episodes
- memory extraction result handling
- face-recognition encounter compatibility
- Slack background enable/disable behavior
- Slack temporary-to-canonical identity convergence
- archive and re-enrollment behavior
- replacement or retirement path for the old `memory.manage_memory` CLI

Tailwag-side smoke checks before a package-facing handoff:

```bash
PYTHONPATH=src python3 -m unittest tests.test_models tests.test_examples
PYTHONPATH=src python3 -m unittest discover -s tests
tailwag schema init --help
tailwag episode create --help
tailwag memory extract --help
tailwag memory consolidate --help
tailwag person context --help
```
