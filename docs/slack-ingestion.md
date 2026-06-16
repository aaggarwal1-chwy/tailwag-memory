# Slack Ingestion Guide

## Purpose

Slack ingestion polls a Slack channel and creates normal `Episode` memories from channel messages and thread replies.

The adapter does not add Slack-specific Neo4j labels or relationships. It maps Slack into the current memory model:

- Slack channel: `Place` with `building_code="SLACK"` and `room_id=<channel_id>`
- Slack thread/root message: `Episode` with ID `slack:<channel_id>:<thread_ts>`
- Slack user: `Person` with ID `slack:<user_id>`
- Slack user email: stored on `Person.email` when available
- Slack participation: `PARTICIPATED_IN` with `source="slack"` and `role="speaker"`

Slack-created people do not include face or audio embeddings. Email is identity evidence for a future linking agent; it does not replace the Slack-owned `Person.id`.

## Slack App Setup

Add the bot token to the ignored repo-local `.env` file:

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

Required bot scopes for public channels:

- `channels:read`
- `channels:history`
- `users:read`
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

Run continuously:

```bash
tailwag slack poll --channel C0123456789 --interval 60
```

The default polling state file is:

```text
.tailwag/slack-state.json
```

Use `--state-file` to override it.

## Inspect Generated Memories

Search generated Slack memories through the CLI:

```bash
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
```

Inspect directly in Neo4j Browser:

```cypher
MATCH (e:Episode)-[:OCCURRED_AT]->(:Place {building_code: "SLACK", room_id: "C0123456789"})
OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(e)
RETURN e.id, e.start_time, e.summary, e.transcript, collect(p.display_name) AS participants
ORDER BY e.start_time DESC
LIMIT 20;
```

## Behavior Notes

- The poller creates one episode per Slack root message or thread.
- Replies update the same stable episode ID instead of creating a new episode.
- Newly seen standalone root messages stay in the active-thread watchlist for `--active-thread-hours` so a later first reply can refresh the same episode. The default watch window is 24 hours.
- Deleted, join, and leave system messages are skipped.
- The state cursor advances only after discovered threads are ingested successfully.
