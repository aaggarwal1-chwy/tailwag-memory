# Memory Endpoints Reference

## Purpose

This document is the caller-facing reference for the Tailwag memory system. It describes the Python endpoints, parameters, return shapes, configuration, and common usage patterns needed to call memory from another repo.

These are synchronous Python APIs, not HTTP endpoints. Normal callers should use `TailwagMemoryClient`; lower-level services are available when a caller needs dependency injection, custom providers, or tests without live OpenAI/Neo4j calls.

## Runtime Setup

Install the package from the consuming repo:

```bash
python -m pip install -e /Users/aaggarwal1/Desktop/code/tailwag-memory
```

Set runtime configuration:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
export OPENAI_API_KEY=sk-your-token-here
export TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
export TAILWAG_EMBEDDING_DIMENSION=64
export TAILWAG_SYNTHESIS_MODEL=gpt-5.5
export SLACK_BOT_TOKEN=xoxb-your-token-here
```

Initialize Neo4j schema once per database:

```python
from tailwag_memory import Neo4jQueryRunner, initialize_schema, load_settings

settings = load_settings()
runner = Neo4jQueryRunner(settings)

try:
    initialize_schema(runner, settings.embedding_dimension)
finally:
    runner.close()
```

`OPENAI_API_KEY` is required for production embeddings, memory extraction, consolidation, vector search, and synthesized person context. Offline tests can inject `MockOpenAIEmbeddingProvider` or fake provider objects into lower-level services.

## Quick Start

```python
from tailwag_memory import EpisodeInput, PersonInput, PlaceInput, TailwagMemoryClient

episode = EpisodeInput(
    id="episode_live_001",
    episode_type="conversation",
    start_time="2026-06-22T14:00:00+00:00",
    end_time="2026-06-22T14:03:00+00:00",
    summary="Jamie prefers Spanish and likes hands-on robot demos.",
    transcript="Jamie: I prefer Spanish and like hands-on robot demos.",
    retention_class="standard",
    place=PlaceInput(building_code="MAIN", room_id="101"),
    participants=[
        PersonInput(
            id="person_jamie",
            display_name="Jamie",
            consent_status="consented",
            role="speaker",
            source="live_chat",
        )
    ],
)

with TailwagMemoryClient.from_env() as memory:
    record = memory.record_episode(episode)
    context = memory.person_context("person_jamie", current_text="robot demo later today")

print(record.episode_id)
print(record.memory_results)
print(context)
```

## High-Level Client Endpoints

Import from the public package facade:

```python
from tailwag_memory import TailwagMemoryClient
```

### `TailwagMemoryClient.from_env()`

Creates a client using `load_settings()` and `Neo4jQueryRunner`.

Parameters: none.

Returns: `TailwagMemoryClient`.

Use as a context manager so the Neo4j driver is closed:

```python
with TailwagMemoryClient.from_env() as memory:
    ...
```

### `upsert_person(person)`

Creates or updates a standalone person profile without recording an episode or event.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `person` | `PersonInput` | yes | Caller-owned person identity/profile payload. |

Returns: `str` person ID.

Notes:

- This endpoint does not generate OpenAI text embeddings and does not require `OPENAI_API_KEY`.
- Omitted profile fields preserve existing `Person` values.
- Person-only upserts mark the person active, clear `archived_at`, and update `last_seen` to the write time.
- Standalone profile writes use `id`, `display_name`, `email`, `consent_status`, `face_embedding`, and `audio_embedding`; `role` and `source` remain episode/event relationship provenance.
- Non-consented `consent_status` values clear stored biometric vectors through the same consent-aware person upsert rules used by episode and event ingestion.

### `archive_person(person_id)`

Archives a person profile by ID.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `person_id` | `str` | yes | Caller-owned `Person.id`. |

Returns: `bool`, true when a matching person was archived.

Notes:

- Archiving preserves historical graph data, including prior episode, event, and memory item relationships.
- Archiving removes stored biometric vectors by clearing `face_embedding` and `audio_embedding`.
- Archived people are excluded from biometric recognition.
- Archived people are not deleted; callers should keep using caller-owned IDs if they need to re-enroll or inspect historical context.
- Archive is not a full retention deletion mechanism; retention and deletion policy remains caller-owned.

### `rekey_person_by_email(email, new_person_id)`

Changes one existing Slack-owned temporary person's `Person.id` to a caller-owned canonical ID by matching their email address.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `email` | `str` | yes | Email identity evidence already stored on exactly one `Person`. |
| `new_person_id` | `str` | yes | New caller-owned canonical `Person.id`. |

Returns: `bool`, true when one person was rekeyed.

Notes:

- This endpoint is intended for Slack-first identity convergence to an Argos canonical ID after Argos confirms the match.
- Rekeying changes the `id` property in place, so existing episode, event, and memory item relationships stay attached to the same graph node.
- Rekeying does not rename existing `MemoryItem.id` values; use person-scoped APIs and relationships after rekey rather than assuming older deterministic memory IDs include the new person ID.
- The operation returns false when the email does not match exactly one person, when the matched person is not the target or a Slack-owned temporary person, or when `new_person_id` is already used by a different `Person` node.
- This endpoint does not generate OpenAI text embeddings and does not require `OPENAI_API_KEY`.

### `record_episode(episode, *, extract_memory=True)`

Stores an episode, place, participants, participant relationships, summary embedding, and transcript embedding. By default it also runs transcript-derived memory extraction for the episode participants.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `episode` | `EpisodeInput` | yes | Caller-owned episode payload. |
| `extract_memory` | `bool` | no | When true, create/update/archive durable person memory items from the transcript after storing the episode. |

Returns: `EpisodeRecordResult`.

Return fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `episode_id` | `str` | Stored episode ID. |
| `memory_results` | `list[PersonMemoryExtractionResult]` | Per-person extraction results. Empty when `extract_memory=False`. |
| `memory_errors` | `list[dict[str, str]]` | Extraction errors by person, if any. Episode storage can still succeed. |

Notes:

- Episode storage always generates text embeddings, so production use requires `OPENAI_API_KEY`.
- `extract_memory=True` uses OpenAI-backed memory extraction.
- Participants with role `speaker` are not required for `record_episode`, but roles help downstream extraction and retrieval semantics.

### `person_context(person_id, limit=10, semantic_scope=None, *, current_text=None, now=None, memory_limit=12, recent_episode_limit=5)`

Returns prompt-ready context for a person. The output combines deterministic durable memory markdown with synthesized context from recent or semantically scoped evidence.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `person_id` | `str` | yes | Caller-owned `Person.id`. |
| `limit` | `int` | no | Maximum related episode/event items used for synthesized context. |
| `semantic_scope` | `str \| None` | no | Topic used to vector-filter episode evidence before synthesis. |
| `current_text` | `str \| None` | no | Current utterance/task used to vector-rank durable memory items. When omitted, `semantic_scope` is reused for durable memory ranking. |
| `now` | `datetime \| None` | no | Reference time for follow-up visibility in deterministic memory context. |
| `memory_limit` | `int` | no | Maximum durable memory lines per section. |
| `recent_episode_limit` | `int` | no | Maximum recent episode summary lines in deterministic memory context. |

Returns: `str`.

Notes:

- If no person exists, synthesized context returns `the database does not have a record of this person`.
- If `semantic_scope` is supplied, an embedding provider is required and unrelated recent history is not used for synthesis.
- The returned string is suitable for prompts, not a structured API contract.

### `extract_memory_for_episode(episode_id, person_id=None)`

Loads a stored episode and runs memory extraction.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `episode_id` | `str` | yes | Stored episode ID. |
| `person_id` | `str \| None` | no | Optional participant to extract for. When omitted, speaker participants are targeted first. |

Returns: `EpisodeMemoryExtractionResult`.

Use this for backfills or debugging extraction after an episode already exists.

### `consolidate_memory(*, person_id=None, all_people=False, person_limit=100, min_evidence_episodes=4, seed_limit=25, neighbor_limit=12, cluster_limit=8, episode_text_limit=1200)`

Consolidates repeated episode evidence into durable per-person memory items.

Parameters:

| Name | Type | Required | Meaning |
| --- | --- | --- | --- |
| `person_id` | `str \| None` | required unless `all_people=True` | Person to consolidate. |
| `all_people` | `bool` | no | Consolidate across people discovered in the graph. |
| `person_limit` | `int` | no | Maximum people to process when `all_people=True`. |
| `min_evidence_episodes` | `int` | no | Minimum distinct supporting episodes required for an operation. Default is 4. |
| `seed_limit` | `int` | no | Number of recent seed episodes for a person. |
| `neighbor_limit` | `int` | no | Semantic neighbors fetched per seed. |
| `cluster_limit` | `int` | no | Maximum candidate clusters sent to the provider. |
| `episode_text_limit` | `int` | no | Maximum text per episode in provider payloads. |

Returns: `MemoryConsolidationResult`.

Notes:

- The service validates provider-supplied supporting episode IDs before writing `SUPPORTED_BY`.
- This is slower background work; normal live ingestion should use `record_episode()`.

## Input Models

Import models from `tailwag_memory`.

### `PersonInput`

Caller-supplied person data.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | `str` | yes | none | Caller-owned person ID. |
| `display_name` | `str \| None` | no | `None` | Human-readable name. |
| `email` | `str \| None` | no | `None` | Optional identity evidence. |
| `consent_status` | `str \| None` | no | `None` | Consent state. Non-consented values clear stored biometric vectors. |
| `face_embedding` | `list[float] \| None` | no | `None` | Caller-supplied face vector. Must match configured dimension. |
| `audio_embedding` | `list[float] \| None` | no | `None` | Caller-supplied audio vector. Must match configured dimension. |
| `role` | `str` | no | `"participant"` | Role on an episode or attendee context. |
| `source` | `str` | no | `"caller"` | Provenance for participation or memory extraction. |

Omitted profile fields preserve existing `Person` values on later writes.

### `PlaceInput`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `building_code` | `str` | yes | Caller-owned building, site, or virtual source code. |
| `room_id` | `str` | yes | Caller-owned room, location, or virtual channel ID. |

### `EpisodeInput`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | `str` | yes | Caller-owned episode ID. |
| `episode_type` | `str` | yes | Example: `conversation`, `encounter`, `slack_thread`. |
| `start_time` | `str` | yes | ISO-8601 timestamp. |
| `end_time` | `str \| None` | yes | ISO-8601 timestamp or `None`. |
| `summary` | `str` | yes | Short text used for storage, retrieval, and embeddings. |
| `transcript` | `str` | yes | Full text evidence. |
| `retention_class` | `str` | yes | Caller-defined retention category. |
| `place` | `PlaceInput` | yes | Episode location. |
| `participants` | `list[PersonInput]` | no | People linked through `PARTICIPATED_IN`. |

`EpisodeInput.from_dict(payload)` parses the same shape from a dictionary.

### `EventInput` And `EventAttendeeInput`

`EventInput` stores place-linked happenings such as scheduled meetings or office events.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | `str` | yes | Caller-owned event ID. |
| `description` | `str` | yes | Event text. |
| `start_time` | `str` | yes | ISO-8601 timestamp. |
| `end_time` | `str \| None` | yes | ISO-8601 timestamp or `None`. |
| `place` | `PlaceInput` | yes | Event location. |
| `accepted_attendees` | `list[EventAttendeeInput]` | yes | Explicit attendee list, or `[]`. |

`EventAttendeeInput` fields:

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `person` | `PersonInput` | yes | none | Attendee person. |
| `response_time` | `str \| None` | no | `None` | RSVP or response timestamp. |
| `source` | `str` | no | `"caller"` | Provenance for attendance. |
| `response` | `str` | no | `"accepted"` | Attendance response. |

`EventInput.from_dict(payload)` parses the same shape from a dictionary.

### `MemoryItemInput`

Advanced callers can mutate durable person memories directly.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `kind` | `str` | yes | none | One of `preference`, `boundary`, `pet`, `fact`, `followup`. |
| `key` | `str` | yes | none | Stable person-scoped key. |
| `summary` | `str` | yes | none | Prompt-visible memory text. |
| `source` | `str` | no | `"caller"` | One of `caller`, `calling-system`, `live_chat`, `slack`, `argos`. Direct memory item writes reject other values. |
| `source_ref` | `str` | no | `""` | Caller/source reference such as an episode ID. |
| `status` | `str` | no | `"active"` | One of `active`, `archived`, `superseded`. |
| `observed_at` | `str` | no | `""` | ISO-8601 timestamp. Empty means now for create. |
| `due_at` | `str` | no | `""` | Follow-up visibility start. Empty means immediately visible. |
| `expires_at` | `str` | no | `""` | Follow-up expiry. Required for active follow-ups. |
| `metadata` | `dict[str, Any]` | no | `{}` | Structured caller metadata. |
| `memory_id` | `str \| None` | no | `None` | Must match Tailwag deterministic ID if supplied. |

Memory identity is deterministic by `(person_id, kind, key)`.

## Lower-Level Write Endpoints

These services require explicit dependencies. Use them for tests, custom providers, or advanced orchestration.

### `EpisodeIngestionService(runner, embeddings).ingest(episode)`

Stores an episode without running durable memory extraction.

Parameters:

| Name | Type | Meaning |
| --- | --- | --- |
| `runner` | `QueryRunner` | Executes Cypher. Usually `Neo4jQueryRunner(settings)`. |
| `embeddings` | `EmbeddingProvider` | Generates summary and transcript embeddings. |
| `episode` | `EpisodeInput` | Episode payload. |

Returns: `str` episode ID.

### `PersonIngestionService(runner)`

Stores standalone person identity/profile updates without episode, event, or OpenAI embedding work.

Methods:

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `upsert(person)` | `PersonInput` | `str` | Create or update a person profile. Omitted fields preserve existing values. |
| `archive(person_id)` | person ID | `bool` | Mark the person archived and clear stored biometric vectors while keeping historical graph data. |
| `rekey_by_email(email, new_person_id)` | email, new person ID | `bool` | Replace one Slack-owned email-matched person's ID with a canonical ID while preserving graph relationships; false when the email or canonical ID is not unique-safe. |

### `EventIngestionService(runner).ingest(event)`

Stores an event, place, accepted attendees, and `ATTENDED` relationships.

Returns: `str` event ID.

### `MemoryItemService`

Constructor:

```python
MemoryItemService(runner, embeddings)
```

Methods:

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `upsert_item(...)` | `person_id`, `item`, `supported_by_episode_id=None` | `str` | Create or replace deterministic person memory. |
| `update_item(...)` | `memory_id`, optional `summary`, `source_ref`, `status`, `observed_at`, `due_at`, `expires_at`, `metadata`, `supported_by_episode_id` | `bool` | Update an existing item. Omitted fields preserve existing values. |
| `archive_item(memory_id)` | `memory_id` | `bool` | Set status to `archived`. |
| `link_supported_episodes(memory_id, episode_ids)` | memory ID and episode IDs | `int` | Link existing episodes as support evidence. |
| `get_item(memory_id)` | memory ID | `MemoryItemResult \| None` | Fetch one memory item. |
| `list_items(...)` | `person_id`, `kinds=()`, `statuses=()`, `source=""`, `limit=100` | `list[MemoryItemResult]` | Fetch filtered memory items. |
| `list_active_items(...)` | `person_id`, `kinds=()`, `source=""`, `now=None`, `limit=100` | `list[MemoryItemResult]` | Fetch active, unexpired items. |
| `vector_search(...)` | `person_id`, `text`, `limit=10`, `now=None` | `list[MemoryItemResult]` | Rank active memory items by summary similarity. |
| `candidate_items(...)` | `person_id`, `transcript`, `limit=12` | `list[MemoryItemResult]` | Select existing memories relevant to extraction. |

## Lower-Level Read Endpoints

### `EpisodeRetrievalService(runner, embeddings)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `by_person(person_id, limit=10)` | person ID | `list[EpisodeMemoryResult]` | Recent episodes linked to a person. |
| `by_place(building_code, room_id, limit=10)` | place key | `list[EpisodeMemoryResult]` | Recent episodes at a place. |
| `vector_search(text, target="summary", limit=10)` | query text, target `summary` or `transcript` | `list[EpisodeMemoryResult]` | Global vector-ranked episode search. |
| `hybrid_search(SearchQuery(...))` | structured query | `list[EpisodeMemoryResult]` | Vector search filtered by person/place. |

`SearchQuery` fields: `text`, optional `person_id`, optional `building_code`, optional `room_id`, `limit=10`, `target="summary"`.

### `EventRetrievalService(runner)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `by_place(building_code, room_id, limit=10)` | place key | `list[EventResult]` | Recent events at a place. |

### `PersonRecognitionService(runner)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `by_face_embedding(embedding, limit=10)` | face vector | `list[PersonRecognitionResult]` | Consented people ranked by face similarity. |
| `by_audio_embedding(embedding, limit=10)` | audio vector | `list[PersonRecognitionResult]` | Consented people ranked by audio similarity. |

Only people with `consent_status="consented"` are returned.

### `PersonContextRetrievalService(runner, embeddings=None)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `source_for_person(person_id, limit=10, semantic_scope=None)` | person ID and optional scope | `PersonContextSource \| None` | Structured recent or scoped evidence for synthesis. |

When `semantic_scope` is provided, `embeddings` is required.

### `PersonMemoryContextService(runner, embeddings=None)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `markdown_for_person(...)` | `person_id`, optional `current_text`, `now`, `memory_limit`, `recent_episode_limit` | `str` | Deterministic durable memory and recent episode markdown. |

## Extraction And Consolidation Services

Most callers should use the high-level client. Use these services to inject custom providers.

### `EpisodeMemoryExtractionService(runner, embeddings, extraction_provider)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `extract_for_episode(...)` | `episode`, optional `person_id`, `speaker_only=False` | `EpisodeMemoryExtractionResult` | Extract memory from a provided episode payload. |
| `extract_for_stored_episode(...)` | `episode_id`, optional `person_id`, `speaker_only=True` | `EpisodeMemoryExtractionResult` | Load an episode from Neo4j and extract memory. |
| `load_episode(episode_id)` | episode ID | `EpisodeInput` | Rebuild stored episode input. |

### `MemoryConsolidationService(runner, embeddings, consolidation_provider)`

| Endpoint | Parameters | Returns | Meaning |
| --- | --- | --- | --- |
| `consolidate_person(...)` | `person_id`, `min_evidence_episodes=4`, `seed_limit=25`, `neighbor_limit=12`, `cluster_limit=8`, `episode_text_limit=1200` | `PersonMemoryConsolidationResult` | Consolidate repeated evidence for one person. |
| `consolidate_all(...)` | `person_limit=100`, `min_evidence_episodes=4`, `seed_limit=25`, `neighbor_limit=12`, `cluster_limit=8`, `episode_text_limit=1200` | `MemoryConsolidationResult` | Consolidate across people. |

## Slack Endpoints

Slack management is Tailwag-owned. Downstream systems should ingest Slack through Tailwag and consume the resulting memories through normal person/place/context retrieval.

Import Slack APIs from the module, not the top-level package:

```python
from pathlib import Path

from tailwag_memory import TailwagMemoryClient, load_settings
from tailwag_memory.slack_ingestion import SlackMemoryPoller, SlackWebApiClient

settings = load_settings()

with TailwagMemoryClient.from_env() as memory:
    slack = SlackWebApiClient(settings.slack_bot_token, include_email=True)
    poller = SlackMemoryPoller(
        client=slack,
        episode_recorder=memory,
        state_path=Path(".tailwag/slack-state.json"),
    )
    result = poller.poll_once("C0123456789", backfill_hours=2)

print(result.ingested_episode_ids)
```

### `SlackWebApiClient(token, *, include_email=False)`

Fetches Slack history, replies, and user profiles through the Slack Web API.

### `SlackMemoryPoller(client, episode_recorder, state_path, *, retention_class="standard", active_thread_hours=24.0, person_id_resolver=None)`

Creates a poller that converts Slack threads into Tailwag episodes.

Constructor parameters:

| Name | Type | Meaning |
| --- | --- | --- |
| `client` | `SlackConversationClient` | Slack API client or test fake. |
| `episode_recorder` | `EpisodeRecorder` | Object with `record_episode(episode, extract_memory=True)`. `TailwagMemoryClient` satisfies this and also exposes canonical email resolution. |
| `state_path` | `Path` | JSON cursor state file. |
| `retention_class` | `str` | Retention class assigned to Slack episodes. |
| `active_thread_hours` | `float` | How long standalone roots stay active for later replies. |
| `person_id_resolver` | `Callable[[str], str \| None] \| None` | Optional normalized-email resolver. When omitted, the poller uses `episode_recorder.canonical_person_id_by_email` when available. |

### `poll_once(channel, *, backfill_hours=None, force_backfill=False, history_limit=200, reply_limit=200, extract_memory=True)`

Runs one Slack channel polling pass.

Parameters:

| Name | Type | Meaning |
| --- | --- | --- |
| `channel` | `str` | Slack channel ID. |
| `backfill_hours` | `float \| None` | Initial lookback when no cursor exists, or forced replay window. |
| `force_backfill` | `bool` | Ignore saved cursor and replay the backfill window. Requires `backfill_hours`. |
| `history_limit` | `int` | Maximum channel history messages fetched per pass. |
| `reply_limit` | `int` | Maximum replies fetched per thread. |
| `extract_memory` | `bool` | Whether recorded episodes run memory extraction. |

Returns: `SlackPollResult`.

Return fields:

| Field | Meaning |
| --- | --- |
| `channel` | Slack channel ID. |
| `checked_threads` | Thread roots evaluated. |
| `ingested_threads` | Threads recorded as episodes. |
| `latest_history_ts` | Saved Slack history cursor. |
| `armed_without_backfill` | True when first run only initialized the cursor. |
| `memory_extraction_enabled` | Whether extraction was requested. |
| `ingested_episode_ids` | Recorded episode IDs. |
| `episode_records` | `EpisodeRecordResult` values from recording. |

### `build_episode_from_slack_thread(channel, messages, client, retention_class="standard", person_id_resolver=None)`

Converts raw Slack messages into an `EpisodeInput` without writing it.

Slack mapping:

- Slack channel becomes `PlaceInput(building_code="SLACK", room_id=<channel_id>)`.
- Slack thread/root becomes `EpisodeInput.id="slack:<channel_id>:<thread_ts>"`.
- Slack users become an existing canonical Argos `person_*` when `person_id_resolver` returns one for the normalized Slack profile email.
- Unresolved Slack users become `PersonInput.id="slack:<user_id>"`.
- Optional Slack email is stored on unresolved Slack-owned `Person.email` only when `include_email=True`.
- Canonical-resolved Slack participants do not send Slack display name or email into person upsert; the Slack display name is kept in transcript text.

## Result Models

Common return types:

| Type | Important fields |
| --- | --- |
| `EpisodeMemoryResult` | `episode_id`, `summary`, `transcript`, optional `score`. |
| `EventResult` | `event_id`, `description`, `start_time`, `end_time`, `building_code`, `room_id`. |
| `PersonRecognitionResult` | `person_id`, `display_name`, `consent_status`, `last_seen`, optional `score`. |
| `PersonContextSource` | `person_id`, `display_name`, `items`. |
| `PersonContextItem` | `item_id`, `item_type`, `text`, timestamps, place, role, source, score, transcript lines. |
| `MemoryItemResult` | `memory_id`, `person_id`, `kind`, `key`, `summary`, `source`, status/timestamps, metadata, optional `score`. |
| `PersonMemoryExtractionResult` | `person_id`, `update_requested`, created/updated/archived IDs, skipped ops, optional error. |
| `EpisodeMemoryExtractionResult` | `episode_id`, per-person memory results, memory errors. |
| `PersonMemoryConsolidationResult` | `person_id`, update flag, created/updated/archived IDs, skipped ops, candidate episode IDs, provider flag, optional error. |
| `MemoryConsolidationResult` | per-person consolidation results and errors. |
| `EpisodeRecordResult` | stored episode ID plus extraction result fields. |

## Operational Rules

- Caller-owned IDs are the stable integration keys. Do not use Neo4j internal IDs.
- Run schema initialization before ingestion or retrieval.
- The configured embedding dimension must match Neo4j vector indexes and supplied biometric vectors.
- Do not pass raw face images or raw audio into Tailwag. Pass embeddings only.
- Direct memory item writes are advanced. Prefer episode recording plus extraction for live systems.
- `fact` memories must remain narrow person-prompt context, not broad ontology facts.
- `SemanticFact`, confidence fields, `org_id`, external vector stores, and secondary persistence are outside current scope.
