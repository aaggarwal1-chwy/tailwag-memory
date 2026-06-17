# Python Package Integration Guide

## Purpose

`tailwag-memory` is intended to be used by another Python repo as a package. The calling system owns IDs, generates or supplies biometric embeddings, and calls the memory services directly.

The package connects to Neo4j through environment variables and stores:

- episodes
- events
- people
- places
- episode text embeddings
- optional person face embeddings
- optional person audio embeddings
- natural-language person context generated from recent related episodes and accepted-attendee events

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
export TAILWAG_SYNTHESIS_MODEL=gpt-5.5
export SLACK_BOT_TOKEN=xoxb-your-token-here
```

The embedding dimension must match every vector index and vector payload used by the service.
`OPENAI_API_KEY` is required for production episode embeddings, vector search, and person context synthesis. Tests should inject `MockOpenAIEmbeddingProvider` or fake synthesis providers instead of calling OpenAI.
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
tailwag episode create --file examples/episode.json
```

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
tailwag person search-face --embedding-file examples/face-embedding.json
tailwag person search-audio --embedding-file examples/audio-embedding.json
```

## Initialize Schema

Run this once per Neo4j database:

```python
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.schema import initialize_schema

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
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.embeddings import OpenAIEmbeddingProvider
from tailwag_memory.ingestion import EpisodeIngestionService
from tailwag_memory.models import EpisodeInput, PersonInput, PlaceInput

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

Slack channel polling creates normal conversation episodes. The channel is stored as a virtual place with `building_code="SLACK"` and `room_id` set to the Slack channel ID. Slack users become people with IDs such as `slack:U0123456789`; email is stored separately on `Person.email` when Slack provides it, and face and audio embeddings are left unset. Slack transcripts resolve user mentions to display names and include timestamped speaker lines. Slack episode summaries include the root speaker name to preserve attribution when a person context paragraph is synthesized later.

```bash
tailwag slack poll --channel C0123456789 --once
```

The first run without `--backfill-hours` starts the cursor at the current time. To import recent existing activity for testing:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
```

After wiping Neo4j data, use `--force-backfill` to ignore the saved polling cursor and repopulate from the requested backfill window:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
```

Run continuous polling:

```bash
tailwag slack poll --channel C0123456789 --interval 60
```

Polling state is stored in `.tailwag/slack-state.json` by default. The poller refreshes active threads so new replies update the same stable episode ID: `slack:<channel_id>:<thread_ts>`.

To inspect generated Slack memories through retrieval, search the Slack virtual place:

```bash
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
```

Public channel polling needs `channels:read`, `channels:history`, `users:read`, and `users:read.email`. Private channel polling also needs `groups:read` and `groups:history`, and the Slack app must be invited to the private channel. See [Slack ingestion guide](slack-ingestion.md) for operator details.

## Create A Place Event

Events represent something that happened, is happening, or is scheduled to happen in a place. Events include an explicit `accepted_attendees` list; pass an empty list when no attendees are known.

```python
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.ingestion import EventIngestionService
from tailwag_memory.models import EventAttendeeInput, EventInput, PersonInput, PlaceInput

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

from tailwag_memory.models import EpisodeInput

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

from tailwag_memory.models import EventInput

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
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.embeddings import OpenAIEmbeddingProvider
from tailwag_memory.models import SearchQuery
from tailwag_memory.retrieval import EpisodeRetrievalService

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

For a social agent that needs natural-language context about a person, use the high-level client and pass only the caller-owned person ID:

```python
from tailwag_memory.client import TailwagMemoryClient

with TailwagMemoryClient.from_env() as memory:
    paragraph = memory.person_context("person_jamie")

print(paragraph)
```

To forcibly narrow the evidence by topic, pass `semantic_scope`. This runs vector search over episode summaries and transcripts for that person before synthesis:

```python
with TailwagMemoryClient.from_env() as memory:
    paragraph = memory.person_context("person_jamie", semantic_scope="chargers")
```

The paragraph combines recent episodes where the person participated and recent events where the person is an accepted attendee. If no `Person` node exists, the method returns exactly:

```text
the database does not have a record of this person
```

If the person exists but has no related recent events or episodes, the method returns a local deterministic paragraph without calling OpenAI.

Person context synthesis sends OpenAI an explicit `current_time`, evidence timestamps, and structured Slack transcript lines when available. The synthesis prompt tells the model to resolve relative phrases like `today`, `tomorrow`, and `later this week` against the evidence timestamp before suggesting a follow-up, so already elapsed meetings are not treated as upcoming.

Scoped person context is episode-only in the current model. If no vector-matched episodes are found for the person and semantic scope, the method returns a local deterministic paragraph without calling OpenAI. It does not fall back to unrelated recent history or event descriptions.

## Search Events By Place

```python
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.retrieval import EventRetrievalService

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
from tailwag_memory.config import load_settings
from tailwag_memory.db import Neo4jQueryRunner
from tailwag_memory.retrieval import PersonRecognitionService

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
- Set `OPENAI_API_KEY` before production ingestion, vector search, or person context synthesis.
- Send consent/profile information on the first encounter, then reference existing people by ID on later memories.
- Use only `building_code` and `room_id` for places in the current scope.
- Use `Event` for place-linked happenings that may reference people as attendees/participants.
- Do not pass raw face images or raw audio into this package.
- Keep biometric vector usage tied to consent and retention policies in the calling system.
- Episode text is sent to OpenAI for embeddings, and recent person-related evidence is sent to OpenAI for context synthesis.
