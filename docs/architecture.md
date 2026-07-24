# Tailwag Memory Architecture

## Purpose

Tailwag Memory is a compact Neo4j-only memory package. It accepts caller-owned people, narrow robot identity/provenance, places, episodes, and events; stores them as graph records; generates OpenAI-backed text embeddings in production; and returns deterministic/vector-derived person context for downstream agents.

This document is the source of truth for current architecture and scope boundaries. For package API details, see [Memory Endpoints Reference](memory-endpoints.md). For the permission-gated robot relay, see [Robot Message Relay](message-relay.md). For package-consumer and Argos HTTP workflows, see [Python Package Integration Guide](integration-guide.md). For the live AWS topology and operations, see [AWS Deployment And Operations](aws-deployment.md). For local inspection reports, see [Inspect Reference](inspect-reference.md).

## Current Scope

Runtime components:

- `Person`
- `Robot`
- `Episode`
- `Event`
- `Place`
- `MemoryItem`
- `RelayMessage`
- `EmployeeDirectoryRecord`
- `FaceReference`
- `VoiceReference`
- `PARTICIPATED_IN`
- `MENTIONED_IN`
- `OCCURRED_AT`
- `ATTENDED`
- `HAS_DIRECTORY_RECORD`
- `HOME_BASED_AT`
- `HAS_FACE_REFERENCE`
- `HAS_VOICE_REFERENCE`
- `HAS_MEMORY`
- `SUPPORTED_BY`
- `ADDRESSED_BY`
- `SUPERSEDED_BY`
- `SENT_RELAY`
- `FOR_RECIPIENT`
- `ASSIGNED_TO`
- OpenAI-backed episode embeddings
- OpenAI-backed memory item embeddings
- Neo4j 5.26 local Docker runtime
- Neo4j constraints and vector indexes for episode text, biometric reference vectors, and `MemoryItem.summary_embedding`
- deterministic/vector-derived person context with durable memory sections and no episode transcript text
- transcript-derived person memory items
- per-person memory consolidation and merged memories from repeated or related episode evidence into `MemoryItem`
- caller-supplied `FaceReference.embedding`
- caller-supplied `VoiceReference.embedding`
- adaptive biometric reference aggregation with per-reference sample counts
- graph and vector retrieval services
- Snowflake-backed employee directory sync and local JSON directory import
- Slack channel polling into conversation episodes
- episode mention relationships
- source-provided event attendees
- optional read-only inspect reports for follow-up validity, affect, person timelines, and memory items

Excluded from the runtime:

- robot capabilities, sensors, installed software, live operational state, maintenance records, and fleet modeling
- `ObjectConcept`
- `Activity`
- `Utterance`
- `SemanticFact`
- a separate semantic-fact queue or ontology orchestrator
- persistent graph confidence ratings and confidence properties
- `org_id`
- external vector databases
- Postgres or other secondary persistence
- Outlook/Microsoft Graph polling and distribution-list expansion

## Design Boundaries

- Neo4j is the only persistence layer.
- Caller-owned IDs are the stable integration keys for `Person`, `Robot`, `Episode`, and `Event`.
- `Place` identity is `(building_code, room_id)`.
- A directory row with a nonblank `site_code` has exactly one canonical home-base link to `Place(building_code=<site_code>, room_id="__site__")`; Tailwag does not infer room-level employee locations.
- `Robot` is a narrow identity/provenance record. It does not expand Tailwag into robot runtime, telemetry, maintenance, or fleet storage.
- `RelayMessage` is an operational delivery record, not durable person memory.
  Its body is retained permanently under the selected policy even after
  delivery, decline, uncertainty, or expiry.
- Relay concurrency uses explicit temporary Neo4j lock properties and
  post-lock compare-and-set or rate-limit checks. Lock properties are removed
  in the same transaction; there are no persistent relay counters on `Person`
  or `Robot`.
- Production text embeddings use the OpenAI-compatible provider; tests use deterministic mocks.
- Face and voice embeddings are biometric identifiers supplied by the caller or an upstream recognition model. Tailwag stores vectors on `FaceReference` and `VoiceReference` nodes, not raw face images or raw audio.
- `MemoryItem` is the approved narrow path for durable transcript-derived person memory. It is not a broad ontology, triple store, or open-ended semantic fact graph.
- Per-person memory consolidation may use Neo4j episode vector indexes to reduce candidate evidence, but it writes only `MemoryItem` records and `SUPPORTED_BY`/`SUPERSEDED_BY` audit links.
- Follow-up addressing writes `ADDRESSED_BY` audit links from resolved follow-up memories to the episode that resolved them.
- Tailwag does not store persistent graph confidence ratings, `org_id`, or secondary database records.
- Inspection utilities are read-only developer/operator tools for follow-up validity, affect, person timeline, and memory item reports. They may export static HTML/JSON and shared browser assets, but they do not change the core package API, graph schema, or Neo4j records. The affect inspector scores person-episode transcript text on demand from external model folders and does not persist affect values.

## Graph Model

### Person

```cypher
(:Person {
  id,
  display_name,
  official_name,
  email,
  consent_status,
  last_seen,
  status,
  archived_at,
  updated_at,
  created_at
})
```

`Person.id` comes from the calling system. When email is present, Tailwag stores it as `lower(trim(email))`, resolves writes to an existing same-email person before creating a new node, and Neo4j enforces `email` as unique. If an incoming canonical `person_*` ID matches a Slack temporary person by email, Tailwag rekeys that Slack node in place when the canonical ID is available. `last_seen` is updated when the person participates in a newer episode, attends a newer event, or receives an explicit person-only identity upsert.

Archived people keep historical graph data, and recognition/update paths exclude their biometric references. Re-enrollment should use the explicit biometric APIs after the caller decides the identity is active again.

### Robot

```cypher
(:Robot {
  id,
  display_name,
  created_at,
  updated_at
})
```

`Robot.id` is the caller-owned stable identity key. Each episode write updates
`Robot.display_name` to the current caller-supplied name. The
`PARTICIPATED_IN.display_name_at_time` property preserves the name supplied
when that robot was first linked to that episode, while `role` and `source`
record episode provenance. Retrieval results expose the robot node's current
display name plus the relationship role and source; the historical
`display_name_at_time` snapshot remains available in the graph for audit use.

Robot participation never creates a `Person`, updates `Person.last_seen`, or
uses face/voice references. Tailwag does not store robot capabilities, sensors,
software, live state, maintenance, fleet membership, or other operational data.

### EmployeeDirectoryRecord

```cypher
(:EmployeeDirectoryRecord {
  <id>,
  site_code,
  username,
  official_name,
  display_name,
  name,
  employee_email,
  business_title,
  job_family,
  job_family_group,
  job_level,
  c_level,
  manager_name,
  cost_center,
  senior_leadership_team,
  business_function,
  tenure,
  normalized_name,
  token_sorted_name,
  source,
  updated_at,
  created_at
})
```

Directory rows are keyed by `(site_code, username)` and are loaded through
`DirectoryIdentityService.sync_directory_people(...)`,
`sync_directory_from_snowflake(...)`, or `tailwag directory sync`. Snowflake is
the runtime source when the CLI sync command omits `--file`; local JSON records
use the same normalized row shape.

Current reconciliation links people to directory rows by the username portion of
their email. Directory sync also links same-username people while loading rows.
Biometric enrollment and explicit encounter recording can additionally link a
specific directory row when metadata supplies both `username` and `site_code`.
For every row with a nonblank site code, directory sync also merges the canonical
site place `Place(building_code=<site_code>, room_id="__site__")`, removes any
prior `HOME_BASED_AT` link to a different target, and links only the
`EmployeeDirectoryRecord` to that place.
It does not create `Person-HOME_BASED_AT` or room-level home-base relationships.
`<id>` is Neo4j Browser's internal node identifier; Tailwag does not store an
application-level `id` property on `EmployeeDirectoryRecord`.

### Biometric References

```cypher
(:Person)-[:HAS_FACE_REFERENCE]->(:FaceReference {
  id,
  embedding,
  model,
  dimension,
  consent_status,
  status,
  sample_count,
  accepted_update_count,
  target_sample_count,
  aggregate_method,
  metadata_json,
  created_at,
  updated_at
})

(:Person)-[:HAS_VOICE_REFERENCE]->(:VoiceReference {
  id,
  embedding,
  model,
  dimension,
  consent_status,
  status,
  sample_count,
  accepted_update_count,
  target_sample_count,
  aggregate_method,
  metadata_json,
  created_at,
  updated_at
})
```

Initial enrollment sets `sample_count=1` and
`aggregate_method="normalized_running_average"`. Adaptive observations update
the stored embedding only after Tailwag verifies active consent, non-archived
person status, cross-modal evidence, model/dimension compatibility, similarity
thresholds, and `sample_count < target_sample_count`.

### Episode

```cypher
(:Episode {
  id,
  episode_type,
  start_time,
  end_time,
  transcript,
  retention_class,
  created_at,
  updated_at,
  transcript_embedding
})
```

Episodes represent stored interactions such as conversations, encounters, and Slack root messages or threads. `transcript_embedding` is generated by the configured embedding provider. Raw recordings are not stored.

### Event

```cypher
(:Event {
  id,
  description,
  start_time,
  end_time,
  created_at,
  updated_at
})
```

Events represent place-linked happenings such as scheduled meetings or room activity. Events may reference accepted attendees through `ATTENDED` and always link to a `Place` through `OCCURRED_AT`.

### Place

```cypher
(:Place {
  building_code,
  room_id
})
```

`Place` stores only `building_code` and `room_id`.

### MemoryItem

```cypher
(:MemoryItem {
  id,
  kind,
  key,
  summary,
  source,
  source_ref,
  status,
  observed_at,
  due_at,
  expires_at,
  metadata_json,
  created_at,
  updated_at,
  summary_embedding
})
```

Memory items are person-scoped prompt memories extracted from transcripts or written by advanced callers. Allowed kinds are `preference`, `boundary`, `pet`, `fact`, and `followup`.

`fact` must stay narrow: no ontology triples, inferred traits, directory attributes, or general world knowledge. Identity-owned directory facts such as title, team, manager, cost center, business function, and leadership org remain caller-owned.

Memory IDs are opaque, append-only, and generated by Tailwag. `key` is a grouping signal for retrieval, consolidation, and merges; it is not identity. Repeated creates with the same `(person_id, kind, key)` create distinct records unless memory merge creates a replacement memory and marks older records `superseded`. Follow-up extraction can explicitly link an incoming episode as `SUPPORTED_BY` evidence for an existing open follow-up without creating a new memory or addressing the follow-up.

Follow-ups require `expires_at` and are visible when active and the current time is between `due_at` and `expires_at`, inclusive. Missing `due_at` means immediately visible. Extracted follow-ups use the episode time as the evidence-time anchor, should be created only when the transcript states or strongly implies a useful timing window, and are skipped when already expired or when `expires_at` is earlier than `due_at`. Vague short-lived hooks do not become durable person memory. When an incoming episode explicitly resolves a follow-up, Tailwag marks it `status = "addressed"` and writes `(:MemoryItem)-[:ADDRESSED_BY]->(:Episode)` with an `addressed_at` relationship timestamp.

Related or redundant memories can be merged into one active memory. Superseded source memories are retained only as developer audit records, marked `status = "superseded"`, linked through `SUPERSEDED_BY`, and excluded from normal endpoint/query results.

### RelayMessage

```cypher
(:RelayMessage {
  id,
  body,
  metadata_json,
  status,
  sender_email_snapshot,
  recipient_email_snapshot,
  sender_display_name_snapshot,
  recipient_display_name_snapshot,
  assigned_robot_id,
  created_at,
  updated_at,
  deliver_after,
  expires_at,
  claim_token,
  attempt_count
})
```

Relay messages carry exact text for permission-gated robot delivery. Expiry
only ends delivery eligibility; it does not delete or redact `body`. Claim,
permission, playback, delivery, decline, and failure fields are added as the
state machine advances. Temporary `_relay_*` lock/create-token properties are
transaction implementation details and are removed before a successful write
commits.

## Relationships

```cypher
(:Person)-[:PARTICIPATED_IN {
  role,
  source
}]->(:Episode)

(:Robot)-[:PARTICIPATED_IN {
  display_name_at_time,
  role,
  source
}]->(:Episode)

(:Person)-[:MENTIONED_IN {
  source
}]->(:Episode)

(:Episode)-[:OCCURRED_AT]->(:Place)

(:Event)-[:OCCURRED_AT]->(:Place)

(:Person)-[:ATTENDED {
  source,
  response,
  response_time
}]->(:Event)

(:Person)-[:HAS_DIRECTORY_RECORD]->(:EmployeeDirectoryRecord)

(:EmployeeDirectoryRecord)-[:HOME_BASED_AT]->(:Place)

(:Person)-[:HAS_FACE_REFERENCE]->(:FaceReference)

(:Person)-[:HAS_VOICE_REFERENCE]->(:VoiceReference)

(:Person)-[:HAS_MEMORY]->(:MemoryItem)

(:MemoryItem)-[:SUPPORTED_BY]->(:Episode)

(:MemoryItem)-[:ADDRESSED_BY {
  addressed_at,
  updated_at
}]->(:Episode)

(:MemoryItem)-[:SUPERSEDED_BY]->(:MemoryItem)

(:Person)-[:SENT_RELAY]->(:RelayMessage)

(:RelayMessage)-[:FOR_RECIPIENT]->(:Person)

(:RelayMessage)-[:ASSIGNED_TO]->(:Robot)
```

`PARTICIPATED_IN.source` records how the calling system decided the person participated in the episode. Example values include `face_recognition`, `speaker_recognition`, `manual`, `caller`, `demo`, `example`, and `slack`. It is relationship provenance, not a confidence score.

For robot participation, `role` and `source` have the same provenance purpose.
`display_name_at_time` is an immutable per-episode snapshot set when the
relationship is created; the `Robot.display_name` node property is the current
name and may change on a later episode write.

`MENTIONED_IN.source` records how the calling system decided the person was named or referenced in the episode. It does not imply the person was present, does not update `Person.last_seen`, and does not make the person a memory-extraction target.

`ATTENDED.source` records how the calling system determined attendance. `response` and `response_time` preserve caller-supplied attendance state without adding a source-specific graph model.

`HAS_DIRECTORY_RECORD` links a person to one or more Tailwag-owned employee
directory rows used for profile projection and identity resolution. The code
reconciles generic person writes by email username; site-specific
metadata is used only where the caller supplies a site.

`HOME_BASED_AT` links an `EmployeeDirectoryRecord` with a nonblank `site_code`
to its one canonical site-level
`Place(building_code=<site_code>, room_id="__site__")`. No other node type
receives this relationship.

`HAS_FACE_REFERENCE` and `HAS_VOICE_REFERENCE` link people to active or archived
biometric reference nodes. Search and adaptive update paths only consider active,
consented references on non-archived people.

`SUPERSEDED_BY` points from a superseded source memory to the active merged memory that replaces it.

`ADDRESSED_BY` points from an addressed follow-up to the incoming episode that resolved it. The relationship timestamp is the authoritative addressed time; the memory node itself uses `updated_at` for the lifecycle state change.

## Schema

Tailwag initializes these uniqueness constraints:

```cypher
CREATE CONSTRAINT person_id IF NOT EXISTS
FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT person_email IF NOT EXISTS
FOR (p:Person) REQUIRE p.email IS UNIQUE;

CREATE CONSTRAINT episode_id IF NOT EXISTS
FOR (e:Episode) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT robot_id IF NOT EXISTS
FOR (r:Robot) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT event_id IF NOT EXISTS
FOR (e:Event) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT memory_item_id IF NOT EXISTS
FOR (m:MemoryItem) REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT relay_message_id IF NOT EXISTS
FOR (m:RelayMessage) REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT employee_directory_record_key IF NOT EXISTS
FOR (d:EmployeeDirectoryRecord) REQUIRE (d.site_code, d.username) IS UNIQUE;

CREATE CONSTRAINT face_reference_id IF NOT EXISTS
FOR (r:FaceReference) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT voice_reference_id IF NOT EXISTS
FOR (r:VoiceReference) REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT place_key IF NOT EXISTS
FOR (p:Place) REQUIRE (p.building_code, p.room_id) IS UNIQUE;
```

Tailwag initializes vector indexes for:

- `Episode.transcript_embedding`
- `FaceReference.embedding`
- `VoiceReference.embedding`
- `MemoryItem.summary_embedding`

Text embedding dimensions must match the configured Neo4j text vector indexes.
Biometric reference dimensions are model-specific and stored on each reference.
Relay range indexes cover status, assigned-robot delivery ordering, and expiry.

## Write Paths

Episode ingestion stores or updates the episode, upserts person participants, updates participant `Person.last_seen`, upserts narrow robot identities, reconciles person/robot `PARTICIPATED_IN` relationships, upserts mentioned people without updating `last_seen`, creates `MENTIONED_IN` relationships, upserts the place, creates the `OCCURRED_AT` relationship, and generates episode text embeddings. An omitted or empty `robots` list is valid and removes stale robot participation links when an existing episode is rewritten.

High-level episode recording uses episode ingestion and, by default, runs transcript-derived memory extraction for linked participants. Extraction provider operations are `create`, `support`, `address`, and `noop`: `create` writes a new `MemoryItem`, `support` links the incoming episode to an existing open follow-up as evidence, and `address` marks an existing follow-up addressed.

Event ingestion stores or updates the event, upserts the place, creates the event `OCCURRED_AT` relationship, upserts accepted attendees, updates attendee `last_seen`, and writes `ATTENDED` relationships.

Person-only ingestion supports explicit identity/profile refreshes through `upsert_person()`, lifecycle archival through `archive_person()`, and Slack-to-canonical identity convergence through `rekey_person_by_email()`. Biometric writes use the reference APIs, not `PersonInput`.

Relay writes resolve canonical person emails and the authenticated robot, apply
the workplace-safety policy before creation, and enforce the delivery state
machine with compare-and-set guards. Mutations acquire explicit temporary
Neo4j write locks, then re-evaluate the expected state or rate limit while the
lock is held. Create locks the sender; claim locks the assigned robot and
candidate messages; subsequent transitions lock the message. The locks are
removed in the same transaction, and rate limits are derived from relay records
rather than persistent `Person` or `Robot` counters.

## CLI Targeted Deletes

`tailwag db delete-node` is a CLI-only maintenance workflow for permanent targeted
deletes. It is intentionally not exposed as an HTTP endpoint or public
`TailwagMemoryClient` API. The command supports only `Person`, `Episode`, and
`MemoryItem` by application-level `id` and requires `--yes`.

Person deletion removes the `Person`, every `MemoryItem` owned through
`HAS_MEMORY`, and any `FaceReference` or `VoiceReference` owned only by that
person. Episodes where the deleted person is the only participant are deleted
with episode-delete memory cleanup; shared episodes are preserved and lose only
that person's `PARTICIPATED_IN` and `MENTIONED_IN` relationships. `Event` and
`EmployeeDirectoryRecord` nodes are shared/reference data and are preserved;
person deletion removes only the deleted person's `ATTENDED` and
`HAS_DIRECTORY_RECORD` relationships.

Episode deletion preserves linked people and Robot nodes. Memory items supported only by the
deleted episode are deleted; memory items with other supporting episodes keep
those supports and lose only the deleted episode's `SUPPORTED_BY` link.
`ADDRESSED_BY` links to the deleted episode are removed. The linked `Place` is
deleted only when it has no remaining incoming `OCCURRED_AT` or
`HOME_BASED_AT` relationship, so canonical employee home-base Places survive
episode cleanup.

Memory item deletion removes the selected `MemoryItem` and every replacement
reachable through outgoing `SUPERSEDED_BY` relationships. It does not delete
linked people, episodes, events, directory records, biometric references, or
places.

## Read Paths

Tailwag provides graph lookups for episodes by person, robot stable ID, and place; events by place; and biometric person recognition. Episode results include all participating robots, sorted by stable robot ID, with current display name and relationship role/source. Vector retrieval supports episode transcript search, hybrid person/robot/place-filtered episode search, and memory item summary search.

`person_context()` returns one prompt-ready deterministic context surface containing active durable memory items and visible follow-ups. It excludes episode transcript text. When `current_text` or `semantic_scope` is supplied, memory item ranking can use vector similarity without rendering the matching episode transcripts.

### Robot-Scoped Person Memory

The high-level `person_context()` and `search_semantic_memory()` contracts
accept an optional stable `robot_id`. When supplied, episode retrieval includes
episodes with no participating Robot and episodes in which that robot
participated. It excludes episodes attached only to other robots.

Durable memory uses the same evidence visibility rule. A memory is visible when
it has no `SUPPORTED_BY` episode or when at least one supporting episode is
robot-free or includes the requested robot. This any-visible-evidence rule means
a consolidated memory supported by both Cody and Puffle is visible to either,
while a memory supported only by Puffle is not visible to Cody. Omitting or
passing a blank `robot_id` preserves person-wide retrieval for non-robot and
legacy callers.

## Source Adapters

Source adapters convert third-party activity into Tailwag's core input models. Slack polling is the current adapter. It maps:

- Slack channel to `Place(building_code="SLACK", room_id=<channel_id>)`
- Slack root/thread to `Episode(id="slack:<channel_id>:<thread_ts>")`
- Slack users to canonical `person_*` IDs when email resolution is unique and caller-approved, otherwise to temporary `slack:<user_id>` IDs
- Slack participation to `PARTICIPATED_IN {source: "slack", role: "speaker"}`
- Slack user mentions to `MENTIONED_IN {source: "slack"}` without participation or `last_seen` semantics

Slack does not add Slack-specific labels or relationships. See [Slack Ingestion Guide](slack-ingestion.md) for operator setup and polling details.

## Runtime Configuration

Core runtime settings are loaded from environment variables or `.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI. |
| `NEO4J_USER` | `neo4j` | Neo4j username. |
| `NEO4J_PASSWORD` | `tailwag-memory` | Neo4j password. |
| `OPENAI_API_KEY` | unset | Required for OpenAI-backed embeddings, extraction, consolidation, and vector search with the OpenAI provider. |
| `TAILWAG_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model. |
| `TAILWAG_EMBEDDING_DIMENSION` | `64` | Vector dimension used by episode and memory item text embedding indexes. |
| `TAILWAG_FACE_EMBEDDING_DIMENSION` | `512` | Vector dimension used by the `FaceReference.embedding` index. |
| `TAILWAG_VOICE_EMBEDDING_DIMENSION` | `192` | Vector dimension used by the `VoiceReference.embedding` index. |
| `TAILWAG_FACE_EMBEDDING_MODEL` | `facenet` | Upstream face embedding model name stamped on face references and adaptive updates. |
| `TAILWAG_VOICE_EMBEDDING_MODEL` | `speechbrain_ecapa` | Upstream voice embedding model name stamped on voice references and adaptive updates. |
| `TAILWAG_SYNTHESIS_MODEL` | `gpt-5.5` | OpenAI model used by memory extraction and consolidation providers. |
| `TAILWAG_API_BEARER_TOKEN` | unset | Required for optional FastAPI memory routes. `GET /health` remains unauthenticated. |
| `TAILWAG_ROBOT_API_TOKENS_JSON` | `{}` | Required robot-ID-to-bearer-token mapping for relay routes. Tokens must be unique. |
| `TAILWAG_RELAY_POLICY_MODEL` | `gpt-5.5` | OpenAI model used for relay workplace-safety screening. |
| `TAILWAG_RELAY_POLICY_TIMEOUT_SECONDS` | `8` | Safety request timeout; must be from 1 through 10 seconds. |
| `TAILWAG_RELAY_POLICY_MAX_RETRIES` | `1` | Safety request retries; must be 0 or 1. |
| `TAILWAG_API_DOCS_ENABLED` | `false` | Enables `/docs`, `/redoc`, and `/openapi.json` when set to `1`, `true`, `yes`, or `on`. |
| `SLACK_BOT_TOKEN` | unset | Required only when polling Slack. |
| `SNOWFLAKE_ACCOUNT` | unset | Required by `tailwag directory sync` when reading directory rows from Snowflake. |
| `SNOWFLAKE_USER` | unset | Snowflake user for directory sync. |
| `SNOWFLAKE_PASSWORD` | unset | Optional Snowflake password; the code also supports external-browser authentication. |
| `SNOWFLAKE_AUTHENTICATOR` | unset | Optional Snowflake authenticator, such as `externalbrowser`. |
| `SNOWFLAKE_ROLE` | unset | Optional Snowflake role. |
| `SNOWFLAKE_WAREHOUSE` | unset | Optional Snowflake warehouse. |
| `SNOWFLAKE_DATABASE` | unset | Required by the Snowflake connector wrapper. |
| `SNOWFLAKE_SCHEMA` | unset | Optional Snowflake schema. |
| `TAILWAG_AFFECT_FOLD1_MODEL` | unset | Optional external XLM-RoBERTa-large fold 1 model directory for `tailwag inspect affect`. |
| `TAILWAG_AFFECT_FOLD2_MODEL` | unset | Optional external XLM-RoBERTa-large fold 2 model directory for `tailwag inspect affect`. |

`GET /health` is dependency-free liveness. `GET /ready` validates relay auth,
OpenAI configuration, Neo4j connectivity, and the required online relay schema.
Safety timeouts, unavailable providers, and invalid provider configuration map
to HTTP `503`; malformed decisions map to `502`.

## Neo4j Browser IDs

Neo4j Browser shows internal identity fields such as `<id>` and `<elementId>` in addition to application-level key properties.

- `<id>` is Neo4j's internal numeric node or relationship ID.
- `<elementId>` is Neo4j's internal string identifier for a graph element.
- `id` is the application-level identifier for `Person`, `Robot`, `Episode`, `Event`, `MemoryItem`, `FaceReference`, and `VoiceReference`.
- `Place` uses `(building_code, room_id)`.
- `EmployeeDirectoryRecord` uses `(site_code, username)` and does not store an application-level `id` property.

Application code should use application-level keys, not Neo4j internal IDs.

## Runtime Exclusions

`Robot` is limited to stable identity, current display name, and episode
participation provenance. The graph contains no robot capabilities, sensors,
installed software, live operational state, maintenance records, fleet model,
`ObjectConcept`, `Activity`, `Utterance`, or `SemanticFact`. It also contains no
persistent confidence properties, `org_id`, external vector database, or
secondary persistence layer. Durable person memory uses the `MemoryItem` model
described above.
