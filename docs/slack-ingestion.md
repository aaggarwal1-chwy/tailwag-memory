# Slack Ingestion Guide

## Purpose

Slack ingestion polls a Slack channel and creates normal `Episode` memories from channel messages and thread replies.

The adapter does not add Slack-specific Neo4j labels or relationships. It maps Slack into the current memory model:

- Slack channel: `Place` with `building_code="SLACK"` and `room_id=<channel_id>`
- Slack thread/root message: `Episode` with ID `slack:<channel_id>:<thread_ts>`
- Slack user: existing canonical Argos `person_*` when `--include-email` is used and exactly one canonical person already has the Slack profile email; otherwise `Person` with ID `slack:<user_id>`
- Slack user email: stored on unresolved Slack-owned people only when `--include-email` is used and Slack provides it
- Slack participation: `PARTICIPATED_IN` with `source="slack"` and `role="speaker"`

Slack-created people do not include face or audio embeddings. When Slack resolves to an existing canonical Argos person, Slack uses the canonical ID for participation but does not send Slack display name or email into the person upsert, so Argos-owned profile fields remain authoritative. When no canonical email match exists, the Slack-owned temporary person keeps the normalized email as identity evidence; Tailwag uses it to attach later same-email writes and rekeys the temporary Slack ID when a matching canonical `person_*` write arrives.

Slack transcripts resolve user mention tokens such as `<@U0123456789>` to display names and prefix each line with the message timestamp and speaker name. Rendered person context uses bounded recent transcript lines spoken by the target person.

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
from tailwag_memory.slack_ingestion import SlackMemoryPoller, SlackWebApiClient

settings = load_settings()

with TailwagMemoryClient.from_env() as memory:
    slack = SlackWebApiClient(settings.slack_bot_token, include_email=True)
    poller = SlackMemoryPoller(
        client=slack,
        episode_recorder=memory,
        state_path=Path(".tailwag/slack-state.json"),
    )
    result = poller.poll_once(
        "C0123456789",
        backfill_hours=2,
        extract_memory=True,
    )

print(result.ingested_episode_ids)
```

Package callers that need continuous polling own the loop and call `poll_once()` on an interval:

```python
import time
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

`TailwagMemoryClient` satisfies the poller's episode recorder contract, so package-level polling records the same episode and memory extraction result shapes as the CLI. `include_email=True` mirrors `--include-email`; `extract_memory=False` mirrors `--skip-memory-extraction`; `force_backfill=True` requires `backfill_hours`.

The same runtime requirements still apply: the Slack token must have the needed scopes, episode recording needs Neo4j configuration, and production episode embeddings need OpenAI configuration. A first package poll without `backfill_hours` only arms the cursor, just like the CLI. Use `force_backfill=True` only for one-shot package backfills; continuous loops should rely on the saved state cursor so they do not replay the same backfill window.

Advanced callers can pass a fake Slack client that implements `history(channel, oldest, limit)`, `replies(channel, thread_ts, limit)`, and `user_profile(user_id)` for tests, or a custom `person_id_resolver` to map normalized Slack email addresses to caller-owned person IDs. `build_episode_from_slack_thread(channel=..., messages=..., client=...)` is available when a caller wants to convert Slack messages into an `EpisodeInput` without writing it. See [Memory Endpoints Reference](memory-endpoints.md#slack-endpoints) for constructor parameters and return fields.

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
- Deleted, bot, join, and leave system messages are skipped.
- The state cursor advances after an empty history check, or after discovered threads are ingested successfully.
