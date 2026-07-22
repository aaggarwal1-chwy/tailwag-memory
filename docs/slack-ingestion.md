# Slack Ingestion Guide

## Purpose

Slack ingestion polls a Slack channel and creates normal `Episode` memories from channel messages and thread replies.

The adapter does not add Slack-specific Neo4j labels or relationships. It maps Slack into the current memory model:

- Slack channel: `Place` with `building_code="SLACK"` and `room_id=<channel_id>`
- Slack thread/root message: `Episode` with ID `slack:<channel_id>:<thread_ts>`
- Slack user: existing caller-owned canonical `person_*` when `--include-email` is used and exactly one canonical person already has the Slack profile email; otherwise `Person` with ID `slack:<user_id>`
- Slack user email: stored on unresolved Slack-owned people only when `--include-email` is used and Slack provides it
- Slack participation: `PARTICIPATED_IN` with `source="slack"` and `role="speaker"`
- Slack user mentions: `MENTIONED_IN` with `source="slack"` without participation or `last_seen` semantics

Slack ingestion does not create face or voice biometric reference nodes. When Slack resolves to an existing caller-owned canonical person, Slack uses the canonical ID for participation but does not send Slack display name or email into the person upsert, so caller-owned profile fields remain authoritative. When no canonical email match exists, the Slack-owned temporary person keeps the normalized email as identity evidence; Tailwag uses it to attach later same-email writes and rekeys the temporary Slack ID when a matching canonical `person_*` write arrives.

Slack transcripts resolve user mention tokens such as `<@U0123456789>` to display names and prefix each line with the message timestamp and speaker name. The adapter also preserves those mention targets in `EpisodeInput.mentioned_people`, resolving them through the same canonical-email path as speakers. Episode transcripts remain available through episode retrieval and inspection paths, but rendered `person_context` excludes transcript text. Mention-only people are not treated as speakers or memory-extraction targets.

## Slack App Setup

Add the bot token to the ignored repo-local `.env` file:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

Required bot scopes for public channels:

- `channels:read`
- `channels:history`
- `users:read`

Optional bot scope when polling with `--include-email`:

- `users:read.email`

Additional bot scopes for private channels:

- `groups:read`
- `groups:history`

After changing scopes, reinstall the Slack app to the workspace. The app must also be invited to the channel being polled.

## Find A Channel ID

Copy a channel or message link from Slack. The channel ID is the value after `/archives/`.

Example:

```text
https://workspace.slack.com/archives/C0123456789/p1781618988346039
```

Channel ID:

```text
C0123456789
```

Private channels may also use IDs beginning with `G`.

## Poll Commands

Run one poll without importing old messages:

```bash
tailwag slack poll --channel C0123456789 --once
```

The first run without `--backfill-hours` arms the cursor from the current time.

Import recent existing activity for testing:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
```

After wiping Neo4j data, force a backfill even when `.tailwag/slack-state.json` already has a saved cursor:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
```

Use `--include-email` only when you want Slack profile email stored as optional identity evidence:

```bash
tailwag slack poll --channel C0123456789 --once --backfill-hours 2 --include-email
```

Run continuously:

```bash
tailwag slack poll --channel C0123456789 --interval 60
```

The default polling state file is:

```text
.tailwag/slack-state.json
```

Use `--state-file` to override it.

Polling state is written by serializing to a temporary file in the state directory and then replacing the target file. If the existing state file is corrupt or has the wrong JSON shape, polling fails before calling Slack or ingesting episodes. When saving, the poller reloads the current on-disk state and merges the channels touched by this poll so progress for other channels is preserved. The state file is not a file-locking protocol and does not claim concurrent same-channel polling safety.

## Package API

Slack ingestion is also available from Python. Import Slack adapter classes from `tailwag_memory.slack_ingestion`; they are not exported from the top-level `tailwag_memory` package.

```python
from pathlib import Path

from tailwag_memory import TailwagMemoryClient, load_settings
from tailwag_memory.slack_ingestion import SlackFilePollStateStore, SlackMemoryPoller, SlackWebApiClient

settings = load_settings()

with TailwagMemoryClient.from_env() as memory:
    slack = SlackWebApiClient(settings.slack_bot_token, include_email=True)
    poller = SlackMemoryPoller(
        client=slack,
        episode_recorder=memory,
        state_store=SlackFilePollStateStore(Path(".tailwag/slack-state.json")),
    )
    result = poller.poll_once(
        "C0123456789",
        backfill_hours=2,
        extract_memory=True,
        enqueue_memory_extraction=True,
    )

print(result.ingested_episode_ids)
```

Package callers that need continuous polling own the loop and call `poll_once()` on an interval:

```python
import time
from pathlib import Path

from tailwag_memory import TailwagMemoryClient, load_settings
from tailwag_memory.slack_ingestion import SlackFilePollStateStore, SlackMemoryPoller, SlackWebApiClient

settings = load_settings()

with TailwagMemoryClient.from_env() as memory:
    slack = SlackWebApiClient(settings.slack_bot_token, include_email=True)
    poller = SlackMemoryPoller(
        client=slack,
        episode_recorder=memory,
        state_store=SlackFilePollStateStore(Path(".tailwag/slack-state.json")),
        active_thread_hours=24.0,
    )

    while True:
        result = poller.poll_once(
            "C0123456789",
            history_limit=200,
            reply_limit=200,
            extract_memory=True,
        )
        print(result.ingested_episode_ids)
        time.sleep(60)
```

`TailwagMemoryClient` satisfies the poller's `EpisodeRecorder` contract:

```python
def record_episode(
    episode: EpisodeInput,
    *,
    extract_memory: bool = True,
    enqueue_memory_extraction: bool = True,
) -> EpisodeRecordResult: ...
```

`poll_once()` passes `extract_memory` to every episode recording call. When the
recorder accepts `enqueue_memory_extraction` or arbitrary keyword arguments, the
poller also passes the exact `True` or `False` enqueue value selected by the
caller. For compatibility with older recorders that do not accept the enqueue
keyword, the poller omits only that unsupported argument. Custom recorders
should accept both keywords when they need to distinguish deferred extraction
from recording without extraction.

| `extract_memory` | `enqueue_memory_extraction` | `TailwagMemoryClient` behavior |
| --- | --- | --- |
| `True` | either value | Record the episode and extract memory inline. |
| `False` | `True` | Require `TAILWAG_MEMORY_JOBS_QUEUE_URL`, record the episode, and enqueue a `memory_extract_episode` job. |
| `False` | `False` | Record the episode without inline or deferred memory extraction. |

`SlackPollResult.memory_extraction_enabled` mirrors `extract_memory`; it does not
indicate whether deferred extraction was queued or completed. Inspect each
`EpisodeRecordResult.memory_extraction_job_id` in `episode_records` for the
queued job ID. Inline extraction results and per-person errors remain available
in each record's `memory_results` and `memory_errors`.

`include_email=True` mirrors `--include-email`, and `force_backfill=True`
requires `backfill_hours`.

The same runtime requirements still apply: the Slack token must have the needed scopes, episode recording needs Neo4j configuration, and production episode embeddings need OpenAI configuration. A first package poll without `backfill_hours` only arms the cursor, just like the CLI. Use `force_backfill=True` only for one-shot package backfills; continuous loops should rely on the saved state cursor so they do not replay the same backfill window.

Advanced callers can pass a fake Slack client that implements `history(channel, oldest, limit)`, `replies(channel, thread_ts, limit)`, and `user_profile(user_id)` for tests, or a custom `SlackPollStateStore` implementation when polling state should live outside the local JSON file. `SlackFilePollStateStore(Path(...))` preserves the CLI's file-backed behavior. `tailwag_memory.aws.SlackDynamoDBPollStateStore` provides DynamoDB-backed cursor state for AWS workers. Callers can also pass a custom `person_id_resolver` to map normalized Slack email addresses to caller-owned person IDs. `build_episode_from_slack_thread(channel=..., messages=..., client=...)` is available when a caller wants to convert Slack messages into an `EpisodeInput` without writing it. See [Memory Endpoints Reference](memory-endpoints.md#slack-endpoints) for constructor parameters and return fields.

## Inspect Generated Memories

Search generated Slack memories through the CLI:

```bash
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
```

Inspect directly in Neo4j Browser:

```cypher
MATCH (e:Episode)-[:OCCURRED_AT]->(:Place {building_code: "SLACK", room_id: "C0123456789"})
OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(e)
RETURN e.id, e.start_time, e.transcript, collect(p.display_name) AS participants
ORDER BY e.start_time DESC
LIMIT 20;
```

## Behavior Notes

- The poller creates one episode per Slack root message or thread.
- Replies update the same stable episode ID instead of creating a new episode.
- Newly seen standalone root messages stay in the active-thread watchlist for `--active-thread-hours` so a later first reply can refresh the same episode. The default watch window is 24 hours.
- Deleted, bot, join, leave, file-only/empty-text, and messages missing `user` or `ts` are skipped.
- After a successful history poll, the state cursor advances to the latest returned history timestamp, or to the poll start timestamp when history is empty. This can advance even when all returned messages were skipped.

## Mention Semantics

Slack messages with user mention tokens populate `EpisodeInput.mentioned_people`.
Episode ingestion writes `MENTIONED_IN` relationships for those people without
changing participation or `last_seen`.
