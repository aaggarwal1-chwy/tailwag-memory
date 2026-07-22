# Tailwag Integration Guide

## Purpose

`tailwag-memory` can be consumed as a Python package or through its authenticated HTTP
service. The calling system owns IDs, identity decisions, biometric embedding
generation, raw media handling, runtime orchestration, and retention policy.
Tailwag owns durable Neo4j memory storage, embeddings, memory
extraction/consolidation, retrieval, person context, employee-directory row
storage, and source adapters.

This guide stays at the package setup and integration-boundary level. For detailed command syntax, endpoint signatures, payload shapes, and source-adapter operation, use the focused references below.

## Reference Map

- Graph model, runtime scope, and boundaries: [Architecture](architecture.md)
- Python endpoints, HTTP schemas, return shapes, and service constructors: [Memory Endpoints Reference](memory-endpoints.md)
- Live AWS topology, resources, access, deployment, and operations: [AWS Deployment And Operations](aws-deployment.md)
- Local command examples and CLI workflow: [CLI Reference](cli-reference.md)
- Read-only local inspection reports and generated report assets: [Inspect Reference](inspect-reference.md)
- Slack app setup, CLI polling, package-level polling, and Slack state behavior: [Slack Ingestion Guide](slack-ingestion.md)

## Install From Another Local Repo

From the consuming repo, install Tailwag in editable mode, replacing `/path/to/tailwag-memory` with the local checkout path:

```bash
python -m pip install -e /path/to/tailwag-memory
```

For local affect inspection with external XLM-RoBERTa-large fold model directories:

```bash
python -m pip install -e "/path/to/tailwag-memory[affect]"
```

Other inspect reports use the base install. See [Inspect Reference](inspect-reference.md) for follow-up validity, person timeline, memory item, and affect report behavior.

For HTTP serving with FastAPI:

```bash
python -m pip install -e "/path/to/tailwag-memory[api]"
```

For deferred memory extraction through SQS, install the AWS extra in the
process that records the episode and enqueues the extraction job:

```bash
python -m pip install -e "/path/to/tailwag-memory[aws]"
```

Combine extras when the FastAPI service will enqueue deferred extraction:

```bash
python -m pip install -e "/path/to/tailwag-memory[api,aws]"
```

The `aws` extra provides `boto3`. It is required when calling
`record_episode(..., extract_memory=False)` with the default
`enqueue_memory_extraction=True`, along with a configured
`TAILWAG_MEMORY_JOBS_QUEUE_URL`. Inline extraction and the explicit
no-extraction combination (`extract_memory=False`,
`enqueue_memory_extraction=False`) do not require the AWS extra.

The repository includes a production-oriented Docker image for the FastAPI
adapter and AWS worker helpers for polling, memory jobs, and report publishing.
See [AWS Deployment And Operations](aws-deployment.md) for the live cloud
shape, API image workflow, ECS health checks, worker deployment, and Secrets
Manager mapping.

## HTTP Service Integration For Argos Or Another Caller

> **Breaking change:** `recent_episode_limit` is no longer accepted by the person-context HTTP request or Python client. Remove it from callers before upgrading.

Use a deployed Tailwag HTTP service instead of connecting directly to Neo4j or
importing Tailwag's worker internals. Store the deployment-specific URL and
token in the caller's runtime configuration or secret store:

```text
TAILWAG_BASE_URL=<deployment base URL>
TAILWAG_BEARER_TOKEN=<secret value>
```

The variable names are recommended examples; an existing Argos configuration
layer may use different names. The requirements are the same base URL and an
`Authorization: Bearer <token>` header. Never commit the token.

An HTTP-only caller does not need to install the Tailwag package. The sample
adapter below uses `httpx`, which the caller must provide as its own dependency
(for example, `python -m pip install httpx`).

### Minimal provider adapter

The following synchronous adapter shows the caller boundary. A real Argos
provider can place equivalent code in its memory-provider package and register
it through Argos's existing provider factory:

```python
from __future__ import annotations

from typing import Any

import httpx


class TailwagHttpMemoryProvider:
    def __init__(self, base_url: str, bearer_token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def _post(self, request_id: str, payload: dict[str, Any]) -> Any:
        response = self._client.post(
            f"/argos/providers/memory/resources/memory/request/{request_id}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def person_context(self, person_id: str, *, current_text: str = "") -> str:
        result = self._post(
            "person_context",
            {"person_id": person_id, "current_text": current_text},
        )
        return str(result["context_markdown"])

    def record_episode(
        self,
        episode: dict[str, Any],
        *,
        extract_memory: bool = True,
        enqueue_memory_extraction: bool = True,
    ) -> dict[str, Any]:
        return self._post(
            "episodes_record",
            {
                "episode": episode,
                "extract_memory": extract_memory,
                "enqueue_memory_extraction": enqueue_memory_extraction,
            },
        )

    def semantic_search(self, text: str, person_id: str, *, limit: int = 5) -> dict[str, Any]:
        return self._post(
            "semantic_search",
            {"text": text, "person_id": person_id, "limit": limit},
        )
```

Use a context manager or application shutdown hook to close the HTTP client.
An asynchronous caller can implement the same contract with
`httpx.AsyncClient`.

### Argos contract mapping

Argos should:

- call `person_context` before prompt assembly and map `context_markdown` into
  its existing memory/about/follow-up prompt fields
- call `episodes_record` after a live transcript is complete, using
  `episode_type="conversation"`, stable caller-owned person and episode IDs,
  `source="live_chat"` on each applicable participant payload, and a `robots`
  entry for every robot participating in the episode
- call `semantic_search` for explicit memory-search tools and preserve the
  separate `episodes` and `memory_items` response lists
- use the people, identity, profile, biometric, and turn-owner routes when
  those existing Argos workflows require them
- treat Tailwag memory-item IDs as opaque
- retry the same logical episode with the same episode ID

Tailwag owns durable Neo4j memory, extraction, consolidation, retrieval, Slack
ingestion, and the narrow stored robot identity/provenance described below.
Argos continues to own robot identity decisions and all robot runtime behavior,
capabilities, sensors, installed software, live state, maintenance, fleet
management, raw media and transcript production, upstream face/speaker
embeddings, retention decisions, and final prompt assembly.

An episode robot payload has this strict shape:

```json
{
  "id": "cody",
  "display_name": "Cody",
  "role": "host",
  "source": "argos"
}
```

`id` and `display_name` are required; `role` defaults to `"host"` and `source`
defaults to `"argos"`. A later episode may update the robot's current display
name without changing its stable ID. Tailwag preserves the display name from
the first link to each episode as relationship-level `display_name_at_time`.
Episode retrieval returns the current display name with that episode's role and
source; consumers needing the historical name snapshot can query the graph.

Before enabling a source poller in another caller, check the current deployment
ownership in [AWS Deployment And Operations](aws-deployment.md) to avoid
polling the same source twice.

Slack-created temporary people can use IDs such as `slack:<user_id>`. When
Argos confirms a canonical identity by email, use the rekey-by-email operation
so existing graph relationships and memories remain attached to the same
person node.

### Caller rollout checklist

1. Confirm the caller can resolve and reach the configured Tailwag base URL.
2. Load the bearer token from the caller's secret store.
3. Check unauthenticated `/health`.
4. Check authenticated
   `/argos/providers/memory/resources/memory/health`.
5. Request context for a known test person and consume `context_markdown`.
6. Record an idempotent test episode.
7. Confirm that subsequent context or semantic search includes the episode.
8. Run the caller's provider/factory and prompt-mapping tests.

For copyable curl commands and discovery of the current endpoint, token secret,
and source-polling ownership, see
[Connect A Caller Such As Argos](aws-deployment.md#connect-a-caller-such-as-argos).

## Runtime Configuration

The following direct runtime configuration applies when the consuming process
imports the Tailwag Python package or runs the Tailwag API. An HTTP-only caller
such as Argos needs only its Tailwag base URL and bearer token.

Set package/runtime configuration in the consuming process or its environment:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=tailwag-memory
export OPENAI_API_KEY=sk-your-token-here
export TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
export TAILWAG_EMBEDDING_DIMENSION=64
export TAILWAG_FACE_EMBEDDING_DIMENSION=512
export TAILWAG_VOICE_EMBEDDING_DIMENSION=192
export TAILWAG_FACE_EMBEDDING_MODEL=facenet
export TAILWAG_VOICE_EMBEDDING_MODEL=speechbrain_ecapa
export TAILWAG_SYNTHESIS_MODEL=gpt-5.5
export TAILWAG_API_BEARER_TOKEN=replace-with-a-private-token
export TAILWAG_API_DOCS_ENABLED=false
export SLACK_BOT_TOKEN=xoxb-your-token-here
export SNOWFLAKE_ACCOUNT=CHEWY-CHEWY
export SNOWFLAKE_USER=<username>@CHEWY.COM
export SNOWFLAKE_PASSWORD=
export SNOWFLAKE_AUTHENTICATOR=externalbrowser
export SNOWFLAKE_ROLE=X_EDLDB_USER
export SNOWFLAKE_WAREHOUSE=SNOWFLAKE_LEARNING_WH
export SNOWFLAKE_DATABASE=EDLDB
export SNOWFLAKE_SCHEMA=CHEWYBI
```

Configuration notes:

- `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` are required for live storage and retrieval.
- `OPENAI_API_KEY` is required when production code uses OpenAI-backed text embeddings, memory extraction, consolidation, or vector search.
- `TAILWAG_EMBEDDING_DIMENSION` must match Neo4j text vector indexes for episode and memory item embeddings.
- `TAILWAG_FACE_EMBEDDING_DIMENSION` and `TAILWAG_VOICE_EMBEDDING_DIMENSION` must match the configured face and voice reference vector indexes.
- `TAILWAG_FACE_EMBEDDING_MODEL` and `TAILWAG_VOICE_EMBEDDING_MODEL` identify the one supported upstream biometric model per modality. Tailwag stores those names on references and rejects adaptive updates when stored references were created with a different configured model.
- `TAILWAG_SYNTHESIS_MODEL` controls the OpenAI model used by memory extraction and consolidation providers.
- `TAILWAG_API_BEARER_TOKEN` is required for the FastAPI memory routes. `GET /health` is unauthenticated for container and load-balancer health checks.
- `TAILWAG_API_DOCS_ENABLED=true` exposes `/docs`, `/redoc`, and `/openapi.json`; leave it false or unset in production unless schema docs are intentionally exposed behind a trusted boundary.
- `SLACK_BOT_TOKEN` is only required when polling Slack.
- `SNOWFLAKE_*` variables are only required when using `sync_directory_from_snowflake()` or `tailwag directory sync` without `--file`. The Snowflake connector is currently a base package dependency because directory sync is part of the current CLI/API surface.
- `TAILWAG_AFFECT_FOLD1_MODEL` and `TAILWAG_AFFECT_FOLD2_MODEL` are optional paths used only by `tailwag inspect affect`.

## Setup Sequence

1. Start or connect to a Neo4j database.
2. Install the Tailwag package in the consuming environment.
3. Set the runtime configuration above.
4. Initialize Tailwag's Neo4j schema once per database.
5. Use the high-level `TailwagMemoryClient` for normal package integration.
6. Use lower-level services only when you need dependency injection, custom providers, or offline tests.

See [Memory Endpoints Reference](memory-endpoints.md#runtime-setup) for schema initialization code and [CLI Reference](cli-reference.md#schema-and-local-data) for local command examples.

## Integration Responsibilities

The consuming system should provide:

- stable caller-owned `Person.id`, `Robot.id`, `Episode.id`, and `Event.id` values
- current robot display names and per-episode robot role/source provenance
- person identity and re-enrollment decisions
- consent status and retention policy
- employee directory rows or Snowflake credentials when using Tailwag directory identity features
- face and voice embeddings from upstream recognition models, passed through Tailwag's biometric reference APIs when durable biometric state is intended
- raw transcript, place, participant, and event payloads
- Slack channel IDs and bot credentials when using Slack ingestion

Tailwag provides:

- schema initialization for the approved Neo4j graph model
- episode, event, person, and memory item storage
- narrow robot identity and episode participation provenance storage
- OpenAI-backed episode and memory item embeddings
- transcript-derived memory extraction and per-person memory consolidation
- employee directory sync, fuzzy identity resolution, verified profile projection, and person encounter recording
- graph, vector, biometric, and person-context retrieval
- biometric reference enrollment/search and adaptive reference aggregation
- Slack source adapter mapping into normal Tailwag episodes

## Public API Surface

Normal package consumers should start with:

```python
from tailwag_memory import TailwagMemoryClient
```

`TailwagMemoryClient` exposes the high-level calls for person profile updates, archiving, email-based rekeying, directory sync and identity resolution, biometric reference enrollment/search/update, turn-owner resolution, episode recording, memory extraction/backfill, memory consolidation, prompt-ready person context, and structured semantic search across a person's episodes and memory items. Detailed method signatures and return shapes live in [Memory Endpoints Reference](memory-endpoints.md#high-level-client-endpoints).

Lower-level services are public for advanced cases such as test fakes, custom embedding providers, source adapters, direct memory item operations, or robot-filtered episode retrieval through `EpisodeRetrievalService.by_robot(...)` and `SearchQuery.robot_id`. Their constructor and method details also live in the endpoint reference.

Robot filtering is not currently exposed by the high-level
`person_context(...)` or `search_semantic_memory(...)` contracts. See the
[architecture gap](architecture.md#future-gap-robot-scoped-person-memory)
before adding or emulating that behavior.

Slack adapter classes are imported from `tailwag_memory.slack_ingestion`, not from the top-level package. Package callers construct a `SlackPollStateStore` explicitly; use `SlackFilePollStateStore(Path(...))` for local JSON cursor state and `tailwag_memory.aws.SlackDynamoDBPollStateStore` for AWS DynamoDB-backed cursor state. See [Slack Ingestion Guide](slack-ingestion.md#package-api).

Inspection helpers are imported from `tailwag_memory.inspect`, not from the top-level package. They are intended for local investigation and reporting, not for normal memory-service integration.

The optional FastAPI adapter mirrors the Argos-facing package operations for service deployments under `/argos/providers/memory/resources/memory/request/{request_id}`. It includes episode recording, semantic search, identity/profile lookups, markdown person context, biometric search/enrollment/observation, voice-reference checks, and turn-owner resolution. Biometric HTTP routes accept embeddings only; raw images, raw audio, media URLs, and base64 media fields are rejected. See [Optional HTTP Endpoints](memory-endpoints.md#optional-http-endpoints) for the full route list, auth, docs exposure, and local run commands.

## Operational Notes

- Run schema initialization before ingestion or retrieval.
- Use caller-owned IDs; do not use Neo4j internal `<id>` or `<elementId>` values as integration keys.
- Directory rows with a nonblank site code link only from `EmployeeDirectoryRecord` to the canonical `Place(building_code=<site_code>, room_id="__site__")` through `HOME_BASED_AT`; do not treat this as a person's room-level location.
- Do not pass raw face images or raw audio into Tailwag. Pass embeddings only.
- Keep biometric vector usage tied to consent and retention policies in the calling system.
- Use `enroll_face_reference()` / `enroll_voice_reference()` for first durable samples, and `observe_face_embedding()` / `observe_voice_embedding()` for cross-modal-safe adaptive updates. Tailwag owns sample counts, similarity thresholds, and completion.
- Direct memory item writes are advanced. Prefer episode recording plus extraction for live systems.
- `fact` memories must remain narrow person-prompt context, not broad ontology facts.
- Robot capabilities, sensors, installed software, live operational state, maintenance records, and fleet modeling are outside current scope; Tailwag stores only robot ID/current name and episode name/role/source provenance.
- `ObjectConcept`, `Activity`, `Utterance`, `SemanticFact`, persistent graph confidence fields, `org_id`, external vector stores, and secondary persistence are outside current scope.
