# Python Package Integration Guide

## Purpose

`tailwag-memory` is intended to be used by another Python repo as a package. The calling system owns IDs, generates or supplies biometric embeddings, and calls the memory services directly.

For a concise reference to the Python memory endpoints, parameters, and return shapes, see [Memory Endpoints Reference](memory-endpoints.md).

The package connects to Neo4j through environment variables and stores:

- episodes
- events
- memory items
- people
- places
- episode text embeddings
- memory item summary embeddings
- optional person face embeddings
- optional person audio embeddings
- deterministic/vector-derived person context assembled from durable memory items, visible follow-ups, and recent episode lines

## Install From Another Local Repo

From the consuming repo, install this package in editable mode:

```bash
python -m pip install -e /Users/aaggarwal1/Desktop/code/tailwag-memory
```

For local development with test dependencies:

```bash
python -m pip install -e "/Users/aaggarwal1/Desktop/code/tailwag-memory[dev]"
```

## Runtime Configuration

Set these environment variables in the consuming repo or process:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
export OPENAI_API_KEY=sk-your-token-here
export TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
export TAILWAG_EMBEDDING_DIMENSION=64
export SLACK_BOT_TOKEN=xoxb-your-token-here
```

The embedding dimension must match every vector index and vector payload used by the service.
`OPENAI_API_KEY` is required when production code uses the OpenAI provider for episode embeddings, memory item embeddings, vector search, memory extraction, or consolidation. Tests should inject `MockOpenAIEmbeddingProvider` or fake providers instead of calling OpenAI.
`SLACK_BOT_TOKEN` is only required when polling Slack.

## CLI Workflows

The package installs a `tailwag` command for local schema setup, demo data, ingestion, retrieval, and Slack polling.

Initialize schema:

```bash
tailwag schema init
```

Seed demo data:

```bash
tailwag seed demo
```

Wipe all Neo4j data before re-seeding:

```bash
tailwag db wipe --yes
```

Create an episode from JSON:

```bash
tailwag episode create --file examples/episode.json --skip-memory-extraction
```

Omit `--skip-memory-extraction` when you want the default high-level workflow: store the episode, then run OpenAI-backed transcript memory extraction for the linked participants.

Create a later memory for an existing person by ID:

```bash
tailwag episode create --file examples/existing-person-episode.json
```

Create a place event with accepted attendees:

```bash
tailwag event create --file examples/event.json
```

Search memories and related records:

```bash
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "chargers"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
tailwag event by-place --building-code MAIN --room-id 101
tailwag person context --person-id person_jamie
tailwag person context --person-id person_jamie --semantic-scope "chargers"
tailwag memory extract --episode-id episode_example_001
tailwag memory extract --episode-id episode_example_001 --person-id person_jamie
tailwag memory consolidate --person-id person_jamie
tailwag memory consolidate --all --person-limit 100
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

## Initialize Schema

Run this once per Neo4j database:

```python
from tailwag_memory import Neo4jQueryRunner, initialize_schema, load_settings

settings = load_settings()
runner = Neo4jQueryRunner(settings)

try:
    initialize_schema(runner, settings.embedding_dimension)
finally:
    runner.close()
```

Schema initialization is idempotent.

## Create An Episode

The calling system provides `Person.id` and `Episode.id`.

On the first interaction with a person, include their display name, consent status, and any available recognition vectors. On later interactions, the participant can be referenced by ID only.

```python
from tailwag_memory import (
    EpisodeIngestionService,
    EpisodeInput,
    Neo4jQueryRunner,
    OpenAIEmbeddingProvider,
    PersonInput,
    PlaceInput,
    load_settings,
)

settings = load_settings()
runner = Neo4jQueryRunner(settings)
embeddings = OpenAIEmbeddingProvider(
    api_key=settings.openai_api_key,
    model=settings.embedding_model,
    dimension=settings.embedding_dimension,
)

episode = EpisodeInput(
    id="episode_external_001",
    episode_type="conversation",
    start_time="2026-06-16T14:00:00+00:00",
    end_time="2026-06-16T14:03:00+00:00",
    summary="Jamie asked where the spare laptop chargers are kept.",
    transcript="Jamie: Do we have spare laptop chargers here?",
    retention_class="standard",
    place=PlaceInput(building_code="MAIN", room_id="101"),
    participants=[
        PersonInput(
            id="person_jamie",
            display_name="Jamie",
            email="jamie@example.com",
            consent_status="consented",
            role="speaker",
            source="calling-system",
        )
    ],
)

try:
    service = EpisodeIngestionService(runner, embeddings)
    service.ingest(episode)
finally:
    runner.close()
```

## Create An Episode With Person Recognition Vectors

Face and audio embeddings are optional. They should be generated by the calling system or by upstream face/speaker recognition models. This package stores the vectors; it does not process raw images or raw audio.

```python
person = PersonInput(
    id="person_jamie",
    display_name="Jamie",
    email="jamie@example.com",
    consent_status="consented",
    face_embedding=[0.01] * 64,
    audio_embedding=[0.02] * 64,
    role="speaker",
    source="calling-system",
)
```

The vector length must match `TAILWAG_EMBEDDING_DIMENSION`.

## Create A Memory For An Existing Person

After the first encounter has stored consent and profile information, later episode payloads can reference the person by ID only:

```python
episode = EpisodeInput(
    id="episode_external_002",
    episode_type="conversation",
    start_time="2026-06-16T16:00:00+00:00",
    end_time="2026-06-16T16:02:00+00:00",
    summary="Jamie asked whether the projector was ready.",
    transcript="Jamie: Is the projector ready for the review?",
    retention_class="standard",
    place=PlaceInput(building_code="MAIN", room_id="101"),
    participants=[
        PersonInput(
            id="person_jamie",
            role="speaker",
            source="calling-system",
        )
    ],
)
```

When `display_name`, `email`, `consent_status`, `face_embedding`, or `audio_embedding` are omitted, ingestion preserves the existing values on the `Person` node and only updates `last_seen` plus the participation relationship for the new episode.

## Poll Slack Into Episodes

Slack channel polling creates normal conversation episodes. The channel is stored as a virtual place with `building_code="SLACK"` and `room_id` set to the Slack channel ID. Slack users become people with IDs such as `slack:U0123456789`; email is stored separately on `Person.email` only when `--include-email` is used and Slack provides it, and face and audio embeddings are left unset. Slack transcripts resolve user mentions to display names and include timestamped speaker lines. Slack episode summaries include the root speaker name so deterministic person context keeps thread attribution clear.

```bash
tailwag slack poll --channel C0123456789 --once
```

Slack polling records episodes through the high-level Tailwag client, so it attempts transcript-derived memory extraction by default for each newly ingested or refreshed thread. The JSON output keeps the polling counters and adds `memory_extraction_enabled`, `ingested_episode_ids`, and `episode_records`; each episode record contains the same `memory_results` and `memory_errors` shape returned by `tailwag episode create`.

The first run without `--backfill-hours` starts the cursor at the current time. To import recent existing activity for testing:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
```

After wiping Neo4j data, use `--force-backfill` to ignore the saved polling cursor and repopulate from the requested backfill window:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
```

Use `--skip-memory-extraction` for smoke tests, local imports without OpenAI-backed extraction, or expensive backfills where you only want to store episodes:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill --skip-memory-extraction
```

Run continuous polling:

```bash
tailwag slack poll --channel C0123456789 --interval 60
```

Polling state is stored in `.tailwag/slack-state.json` by default. The poller refreshes active threads so new replies update the same stable episode ID: `slack:<channel_id>:<thread_ts>`. State saves use a temporary file and replace the target state file atomically. A corrupt or invalid state file fails before Slack calls or episode ingestion, and stale saves merge touched channel progress with the latest on-disk state so other channel cursors are preserved. The state file is not a file-locking protocol and does not guarantee concurrent polling of the same channel.

To inspect generated Slack memories through retrieval, search the Slack virtual place:

```bash
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
```

Public channel polling needs `channels:read`, `channels:history`, and `users:read`. Add `users:read.email` only when using `--include-email`. Private channel polling also needs `groups:read` and `groups:history`, and the Slack app must be invited to the private channel. See [Slack ingestion guide](slack-ingestion.md) for operator details.

## Create A Place Event

Events represent something that happened, is happening, or is scheduled to happen in a place. Events include an explicit `accepted_attendees` list; pass an empty list when no attendees are known.

```python
from tailwag_memory import (
    EventAttendeeInput,
    EventIngestionService,
    EventInput,
    Neo4jQueryRunner,
    PersonInput,
    PlaceInput,
    load_settings,
)

settings = load_settings()
runner = Neo4jQueryRunner(settings)

event = EventInput(
    id="event_external_001",
    description="Room 101 was reserved for the afternoon design review.",
    start_time="2026-06-16T15:00:00+00:00",
    end_time="2026-06-16T16:00:00+00:00",
    place=PlaceInput(building_code="MAIN", room_id="101"),
    accepted_attendees=[
        EventAttendeeInput(
            person=PersonInput(
                id="person_jamie",
                display_name="Jamie",
                email="jamie@example.com",
            ),
            response_time="2026-06-15T18:00:00+00:00",
            source="calling-system",
        )
    ],
)

try:
    service = EventIngestionService(runner)
    service.ingest(event)
finally:
    runner.close()
```

## Parse Episode JSON

If the calling repo already has JSON payloads:

```python
import json
from pathlib import Path

from tailwag_memory import EpisodeInput

payload = json.loads(Path("episode.json").read_text())
episode = EpisodeInput.from_dict(payload)
```

Expected JSON shape:

```json
{
  "id": "episode_external_001",
  "episode_type": "conversation",
  "start_time": "2026-06-16T14:00:00+00:00",
  "end_time": "2026-06-16T14:03:00+00:00",
  "summary": "Jamie asked where the spare laptop chargers are kept.",
  "transcript": "Jamie: Do we have spare laptop chargers here?",
  "retention_class": "standard",
  "place": {
    "building_code": "MAIN",
    "room_id": "101"
  },
  "participants": [
    {
      "id": "person_jamie",
      "display_name": "Jamie",
      "email": "jamie@example.com",
      "consent_status": "consented",
      "face_embedding": [0.01],
      "audio_embedding": [0.02],
      "role": "speaker",
      "source": "calling-system"
    }
  ]
}
```

The example above shortens embedding arrays for readability. Real payloads should use vectors with the configured dimension.

For an existing person, the participant can be just:

```json
{
  "id": "person_jamie",
  "role": "speaker",
  "source": "calling-system"
}
```

## Parse Event JSON

```python
import json
from pathlib import Path

from tailwag_memory import EventInput

payload = json.loads(Path("event.json").read_text())
event = EventInput.from_dict(payload)
```

Expected JSON shape:

```json
{
  "id": "event_external_001",
  "description": "Room 101 was reserved for the afternoon design review.",
  "start_time": "2026-06-16T15:00:00+00:00",
  "end_time": "2026-06-16T16:00:00+00:00",
  "place": {
    "building_code": "MAIN",
    "room_id": "101"
  },
  "accepted_attendees": [
    {
      "person": {
        "id": "person_jamie",
        "display_name": "Jamie",
        "email": "jamie@example.com"
      },
      "response_time": "2026-06-15T18:00:00+00:00",
      "source": "calling-system"
    }
  ]
}
```

Use `"accepted_attendees": []` when no attendee people are known. The field is required so event payloads are explicit about whether attendee data was available.

## Participation Source

`PersonInput.source` is stored on the `PARTICIPATED_IN` relationship. It records how the calling system determined that the person participated in the episode.

Useful values include:

- `face_recognition`
- `speaker_recognition`
- `manual`
- `caller`
- `demo`

For example, a camera pipeline might pass `source="face_recognition"`, while an audio pipeline might pass `source="speaker_recognition"`. This is relationship provenance, not a confidence score. The current implementation does not store confidence ratings.

Event attendee entries store their `source`, `response`, and `response_time` on the `ATTENDED` relationship. The default response is `accepted`, which matches the future Outlook RSVP path without requiring Outlook permissions in the current implementation.

## Neo4j Browser IDs

When you inspect nodes in Neo4j Browser, you may see internal fields such as `<id>` and `<elementId>` alongside the application's `id` property.

- `<id>` is Neo4j's legacy internal numeric ID.
- `<elementId>` is Neo4j's internal string ID.
- `id` is the caller-owned application ID used by this package.

Other repos should use the `id` property, not Neo4j's internal IDs.

## Search Episodes

```python
from tailwag_memory import (
    EpisodeRetrievalService,
    Neo4jQueryRunner,
    OpenAIEmbeddingProvider,
    SearchQuery,
    load_settings,
)

settings = load_settings()
runner = Neo4jQueryRunner(settings)
embeddings = OpenAIEmbeddingProvider(
    api_key=settings.openai_api_key,
    model=settings.embedding_model,
    dimension=settings.embedding_dimension,
)

try:
    service = EpisodeRetrievalService(runner, embeddings)
    results = service.hybrid_search(
        SearchQuery(
            text="chargers",
            person_id="person_jamie",
            building_code="MAIN",
            room_id="101",
            limit=10,
            target="summary",
        )
    )
finally:
    runner.close()

for result in results:
    print(result.episode_id, result.score, result.summary)
```

Other retrieval helpers:

```python
service.by_person("person_jamie")
service.by_place("MAIN", "101")
service.vector_search("chargers", target="summary")
service.vector_search("chargers", target="transcript")
```

## Generate Person Context

For a social agent that needs prompt context about a person, use the high-level client and pass only the caller-owned person ID:

```python
from tailwag_memory import TailwagMemoryClient

with TailwagMemoryClient.from_env() as memory:
    context = memory.person_context("person_jamie")

print(context)
```

`person_context()` returns one deterministic context surface. It includes durable memory sections, visible follow-ups, and a bounded `Recent Episodes` section when available.

To retrieve memory items against the user's current utterance or task, pass `current_text`:

```python
with TailwagMemoryClient.from_env() as memory:
    context = memory.person_context(
        "person_jamie",
        current_text="robot demo later today",
    )
```

To retrieve durable memory items against a topic, pass `semantic_scope`. When `current_text` is omitted, `semantic_scope` is used to retrieve semantically related durable memory items. Rendered episode lines still come from the bounded `Recent Episodes` section:

```python
with TailwagMemoryClient.from_env() as memory:
    context = memory.person_context("person_jamie", semantic_scope="chargers")
```

The returned context combines durable memory items and recent episode lines from episodes where the person participated. If no `Person` node exists and there are no memory items, the method returns exactly:

```text
the database does not have a record of this person
```

If the person exists but has no related episodes, the method returns local deterministic context.

If no vector-matched episodes are found for the person and semantic scope, the method may include a local no-match note. It does not render a separate scoped episode-evidence section.

## Search Events By Place

```python
from tailwag_memory import EventRetrievalService, Neo4jQueryRunner, load_settings

settings = load_settings()
runner = Neo4jQueryRunner(settings)

try:
    service = EventRetrievalService(runner)
    events = service.by_place("MAIN", "101", limit=10)
finally:
    runner.close()

for event in events:
    print(event.event_id, event.start_time, event.description)
```

## Search People By Face Or Audio Embedding

```python
from tailwag_memory import Neo4jQueryRunner, PersonRecognitionService, load_settings

settings = load_settings()
runner = Neo4jQueryRunner(settings)

try:
    service = PersonRecognitionService(runner)
    face_matches = service.by_face_embedding([0.01] * settings.embedding_dimension, limit=5)
    audio_matches = service.by_audio_embedding([0.02] * settings.embedding_dimension, limit=5)
finally:
    runner.close()

for match in face_matches:
    print(match.person_id, match.display_name, match.score)
```

## Replace The Argos Memory Folder

When `argos-agent` replaces its whole `argos_src/memory` folder with this package, the migration should not be treated as a simple import rename. Argos currently uses that folder as a realtime memory runtime: startup wiring, prompt context compilation, face-recognition encounter tracking, live-chat extraction, Slack polling, and memory CLI helpers all call memory APIs directly.

The intended integration is:

- Tailwag owns durable memory storage, episode/event ingestion, memory extraction, vector retrieval, and deterministic/vector-derived person context.
- Argos owns robot/runtime identity, turn ownership, transcription, summaries, face and speaker recognition, profile config, and realtime prompt assembly.
- A small Argos compatibility adapter should keep the old Argos-facing runtime contract while delegating persistence and retrieval to Tailwag.

The adapter should preserve these Argos-facing exports or equivalent call sites:

- `MemoryStore`: backed by Tailwag services instead of SQLite. It should cover `upsert_item`, `update_item`, `archive_item`, `merge_items`, `get_item`, `list_items`, `list_active_items`, plus compatibility methods such as `record_encounter` and `list_recent_encounters`.
- `MemoryContextCompiler`: backed by Tailwag person context and retrieval. It should still expose `person_context(...)` with `profile_lines`, `followup_lines`, and `preferred_language`, and `site_blocks(...)` for prompt-visible location memory.
- `PreferenceExtractor`: convert completed Argos `PreferenceSegment` buffers into `EpisodeInput` records and call `TailwagMemoryClient.record_episode(..., extract_memory=True)`.
- `SlackMemoryService`: either wrap Tailwag Slack polling or intentionally keep Argos background scheduling while writing Slack activity as Tailwag episodes.

Argos startup should construct the adapter where it currently constructs `MemoryStore`, `MemoryContextCompiler`, `PreferenceExtractor`, and `SlackMemoryService`. The old `memory_store.db_path` setting should become deprecated or ignored in Tailwag mode, with Neo4j and OpenAI configuration coming from Tailwag settings or environment variables.

Runtime behavior should map as follows:

- On agent startup, initialize Tailwag configuration and construct the compatibility adapter. Run schema initialization through an operator/admin path, not repeatedly during every realtime turn.
- On each realtime turn, use the adapter compiler to populate the existing Argos prompt fields: person profile lines, follow-up lines, preferred language, and site memory blocks.
- After completed attributed live-chat turns, record one Tailwag conversation episode for the buffered segment and let Tailwag extraction create, update, or archive durable person memory items.
- When face recognition records a recognized interaction, either write a short encounter episode or use a compatibility `record_encounter` implementation that stores short-lived prompt context in Tailwag-backed form.
- When Slack memory is enabled, prefer episode-based Slack ingestion. If Argos keeps its existing background service controls, the service should call Tailwag polling/recording rather than writing SQLite memory operations.
- Keep Argos identity linking explicit. Slack people use existing canonical Argos `person_*` IDs only when Slack email resolves to exactly one canonical person; otherwise they remain temporary `slack:<user_id>` people until Argos supplies a caller-owned `Person.id` and email rekeying converges them.

Compatibility tests in `argos-agent` should cover startup wiring, turn-context prompt output, preferred-language propagation, live-chat segment recording, face-recognition encounter recording, Slack background enable/disable behavior, and any replacement for the old `memory.manage_memory` CLI.

## Enroll Or Update Argos Person Identity

Argos should keep ownership of robot/runtime identity decisions and pass the caller-owned `Person.id` into Tailwag. Use `upsert_person()` when Argos creates or refreshes a known person profile outside a live episode, such as after face enrollment, speaker enrollment, profile import, or a deliberate identity-linking step.

```python
from tailwag_memory import PersonInput, TailwagMemoryClient

person = PersonInput(
    id="argos:person_jamie",
    display_name="Jamie",
    email="jamie@example.com",
    consent_status="consented",
    face_embedding=[0.01] * 64,
    audio_embedding=[0.02] * 64,
)

with TailwagMemoryClient.from_env() as memory:
    person_id = memory.upsert_person(person)
```

Later identity refreshes can send only the fields Argos wants to change. Omitted fields preserve the existing Tailwag `Person` values:

```python
with TailwagMemoryClient.from_env() as memory:
    memory.upsert_person(
        PersonInput(
            id="argos:person_jamie",
            display_name="Jamie A.",
        )
    )
```

When Slack has already created a person such as `slack:U0123456789`, Argos can use Slack/email identity convergence to rekey that node to an Argos canonical ID after it confirms the shared email identity:

```python
with TailwagMemoryClient.from_env() as memory:
    rekeyed = memory.rekey_person_by_email(
        email="jamie@example.com",
        new_person_id="argos:person_jamie",
    )
```

`rekey_person_by_email()` changes one Slack-owned temporary `Person.id` property in place, so existing Slack episodes, events, and memory items stay attached to the same graph node. Existing `MemoryItem.id` values are not renamed, so Argos should treat memory IDs as opaque stable IDs and use person-scoped Tailwag APIs plus graph relationships after rekey rather than assuming older deterministic memory IDs include the new person ID. The method returns `False` when the email does not identify exactly one person, when the matched person is not the target or a Slack-owned temporary person, or when the canonical ID is already used by a different `Person` node. Argos should treat those cases as identity-review work rather than auto-merging people.

If Argos needs to retire an identity or revoke biometric recognition, archive the person instead of deleting the node:

```python
with TailwagMemoryClient.from_env() as memory:
    archived = memory.archive_person("argos:person_jamie")
```

Archived people keep historical graph data, including prior episodes, events, and memory items, so old prompt context and audit trails remain inspectable by caller-owned ID. Archiving removes stored biometric vectors by clearing `face_embedding` and `audio_embedding`, and archived profiles are excluded from biometric recognition. Archive is not a full retention deletion mechanism; retention and deletion policy remains caller-owned.

Re-enrollment is an explicit Argos identity decision. Normal episode or event ingestion can still reference an archived person by ID for historical continuity, but it should not be used to reactivate or reseed biometric vectors for that profile. Call `upsert_person()` after Argos decides the identity should become active again.

`upsert_person()`, `archive_person()`, and `rekey_person_by_email()` do not create episode text embeddings and do not initialize OpenAI-backed embedding providers. They still require Neo4j configuration because they write person records.

## Record Episodes With Internal Memory Extraction

For an Argos-style runtime, new live conversation memory should enter Tailwag as normal episodes through the high-level client. Tailwag stores the episode and internally checks whether transcript-derived memory items should be created, updated, or archived. Argos runtime code should not call low-level memory item services directly except inside a compatibility adapter.

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

`record_episode(..., extract_memory=True)` is the default. If episode storage should run without OpenAI-backed memory extraction, pass `extract_memory=False`.

To backfill or debug memory extraction for an episode that is already in Neo4j:

```python
with TailwagMemoryClient.from_env() as memory:
    result = memory.extract_memory_for_episode(
        "episode_external_001",
        person_id="person_jamie",
    )
```

The record result includes `episode_id`, `memory_results`, and `memory_errors`. Each per-person memory result includes `person_id`, `update_requested`, `created_memory_ids`, `updated_memory_ids`, `archived_memory_ids`, `skipped_ops`, and `error`. `update_requested` reflects extractor intent; actual changes are the non-empty created, updated, or archived lists.

High-level episode recording checks every participant. Existing-episode CLI backfills default to speaker participants, falling back to all participants when no speaker role is present. Use `--person-id` or `person_id=` to narrow extraction for debugging.

## Consolidate Repeated Person Memory Evidence

Episode memory extraction works one episode at a time. For slower background work, Tailwag can also consolidate repeated or related per-person episode evidence into the same `MemoryItem` shape:

```python
with TailwagMemoryClient.from_env() as memory:
    result = memory.consolidate_memory(person_id="person_jamie")
```

For local or scheduled runs, use the CLI:

```bash
tailwag memory consolidate --person-id person_jamie
tailwag memory consolidate --all --person-limit 100
```

The consolidation pass uses Neo4j episode summary vector search to reduce candidate evidence before calling OpenAI. It stays person-scoped, requires four distinct supporting episodes by default, and validates every provider-supplied supporting episode ID against the fetched candidate episodes before writing any `SUPPORTED_BY` relationship. Duplicate episode IDs count once, unknown episode IDs do not count, and operations that fall below the threshold are skipped.

When multiple memories are related but carry distinct useful details, consolidation can create or update one active merged memory that preserves the details in one place. Source memories are marked `superseded`, linked to the merged memory with `SUPERSEDED_BY`, and retained only as developer audit records. Normal endpoint and query APIs do not return superseded memories.

The tunable defaults are intentionally isolated for testing:

```bash
tailwag memory consolidate --person-id person_jamie --min-evidence-episodes 4 --seed-limit 25 --neighbor-limit 12 --cluster-limit 8
```

This is not the deferred semantic consolidation queue and does not add `SemanticFact`, confidence properties, external vector databases, or new graph labels.

Memory extraction supports these person-scoped memory item kinds:

- `preference`: stable likes, dislikes, preferred language/name, and interaction preferences.
- `boundary`: explicit comfort or behavior constraints. These should be included before other memory in prompt context.
- `pet`: named pet records and durable pet updates.
- `fact`: narrow person-prompt context that helps future conversation, such as durable personal projects or recurring personal context. Do not use it for ontology triples, inferred traits, directory attributes, or general world knowledge. `note` is intentionally not a separate kind.
- `followup`: short-lived conversational opportunities. These require `expires_at` and are visible while the current time is between `due_at` and `expires_at`, inclusive. Missing `due_at` means immediately visible.

Memory item identity is person-scoped by `(person_id, kind, key)` at create time, so the same preference or fact extracted from live chat and Slack-derived source adapters converges into one durable memory item. After person rekeying, existing memory IDs remain opaque historical IDs and ownership comes from `HAS_MEMORY`. Slack polling is available through the built-in Source Adapter CLI path and writes the same episode and memory item shapes as caller-supplied records. The extractor rejects identity-owned directory facts such as title, team, manager, cost center, business function, and leadership org. Those should stay in the calling system's identity or directory layer.

## Unified Context Shape

The durable memory portion is a deterministic markdown-style block. Empty sections are omitted, and the block is omitted when there are no active memory items or recent episode lines.

```python
from tailwag_memory import TailwagMemoryClient

with TailwagMemoryClient.from_env() as memory:
    context = memory.person_context(
        "person_jamie",
        current_text="robot demo later today",
    )

print(context)
```

Example output:

```text
[PERSON MEMORY]
Boundaries:
- boundary: avoid loud surprise greetings

Preferences:
- preferred language: Spanish
- likes: hands-on robot demos

Pets:
- pet: Luna (dog): recovering well after surgery

Facts:
- working on robot social memory extraction

Potential Follow-Ups:
- Cape Cod trip with their parents planned for the weekend of 2026-06-20.

Recent Episodes:
- 2026-06-16: Jamie mentioned Luna had a vet visit tomorrow.
```

## Embedding Providers

Production code should use:

```python
OpenAIEmbeddingProvider
```

Tests and offline fixtures should use:

```python
MockOpenAIEmbeddingProvider
```

The consuming repo should depend on the `EmbeddingProvider` behavior rather than on either concrete provider.

## Operational Notes

- Start Neo4j before calling services.
- Run schema initialization before ingestion or retrieval.
- Use caller-owned IDs for people, episodes, and events.
- Set `OPENAI_API_KEY` before production ingestion or vector search when using the OpenAI embedding provider.
- Set `OPENAI_API_KEY` before production transcript memory extraction.
- Send consent/profile information on the first encounter, then reference existing people by ID on later memories.
- Use only `building_code` and `room_id` for places in the current scope.
- Use `Event` for place-linked happenings that may reference people as attendees/participants.
- Do not pass raw face images or raw audio into this package.
- Keep biometric vector usage tied to consent and retention policies in the calling system.
- Episode text and memory item summaries are sent to OpenAI for embeddings when using the OpenAI embedding provider.
- Transcript memory extraction sends transcripts and selected existing memory item candidates to OpenAI.
- `upsert_person()`, `archive_person()`, and `rekey_person_by_email()` are profile-only writes; they do not call OpenAI. Archived people retain historical graph data while stored biometric vectors are removed.
