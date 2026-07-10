# CLI Reference

## Purpose

The `tailwag` command supports local schema setup, ingestion, retrieval, source-adapter polling, and memory maintenance. This reference lists command shapes for local development and smoke testing. For Python package APIs, see [Memory Endpoints Reference](memory-endpoints.md).

Most commands require Neo4j configuration. Commands that create episode embeddings, run memory extraction, run consolidation, or perform OpenAI-backed vector search also require OpenAI configuration.

## Schema And Local Data

Initialize the Neo4j schema:

```bash
tailwag schema init
```

Wipe all Neo4j data before re-running local examples:

```bash
tailwag db wipe --yes
```

## Episode And Event Ingestion

Create an episode from JSON without transcript memory extraction:

```bash
tailwag episode create --file examples/episode.json --skip-memory-extraction
```

Create an episode and run default transcript memory extraction:

```bash
tailwag episode create --file examples/episode.json
```

Create a later episode for an existing person by ID:

```bash
tailwag episode create --file examples/existing-person-episode.json
```

Create a place event with accepted attendees:

```bash
tailwag event create --file examples/event.json
```

## Retrieval

Search memories and related records:

```bash
tailwag search "what did Jamie ask about?"
tailwag search --person-id person_jamie "chargers"
tailwag search --building-code MAIN --room-id 101 "projector"
tailwag search --building-code SLACK --room-id C0123456789 "conversation"
tailwag event by-place --building-code MAIN --room-id 101
```

Generate prompt-ready person context:

```bash
tailwag person context --person-id person_jamie
tailwag person context --person-id person_jamie --semantic-scope "chargers"
tailwag person context --person-id person_jamie --current-text "robot demo later today"
tailwag person context --person-id person_jamie --memory-limit 8 --recent-episode-limit 3
tailwag person profile --person-id person_jamie
```

Sync and resolve employee directory identities:

```bash
tailwag directory sync --site-code BOS3
tailwag directory sync --site-code BOS3 --file path/to/directory-records.json
tailwag identity resolve --site-code BOS3 --first Jamie --last Example
```

`directory sync` reads from Snowflake when `--file` is omitted. The JSON file form is for local fixtures or offline imports of directory records.

Search people by caller-supplied biometric reference vectors:

```bash
tailwag biometric search-face --embedding-file path/to/face-vector.json --site-code BOS3
tailwag biometric search-voice --embedding-file path/to/voice-vector.json --site-code BOS3
```

## Inspect Utilities

Export read-only inspection reports for recent person-episode affect, person timelines, and memory item/follow-up state:

```bash
python3 -m pip install -e ".[affect]"
tailwag inspect affect --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
tailwag inspect affect --person-id person_jamie --limit 25 --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
tailwag inspect affect --format json --output - --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
tailwag inspect person-timeline
tailwag inspect person-timeline --person-id person_jamie --format json --output -
tailwag inspect memory-items
tailwag inspect memory-items --person-id person_jamie --format json --output -
```

The affect utility uses external XLM-RoBERTa-large fold model directories and scores on demand. It does not write scores back to Neo4j. The default export scores the 1000 most recent person-episode pairs; raise or lower that with `--limit` depending on local inference cost. You can also set `TAILWAG_AFFECT_FOLD1_MODEL` and `TAILWAG_AFFECT_FOLD2_MODEL` in `.env` instead of passing model paths every time.

HTML output is the default and writes linked reports under `inspect/` unless `--output` is provided: `inspect/tailwag-affect.html`, `inspect/tailwag-person-timeline.html`, and `inspect/tailwag-memory-items.html`. The repository also includes empty placeholder pages at those paths so the report family can be opened before any database export has run. The scatter plot displays valence and arousal on a centered `-1..1` VAD-style axis; the side panel keeps the model's native `0..1` averaged fold scores visible for comparison. Points with same-person memory item evidence linked to the episode are highlighted with a second color and show the linked memory count in the side panel. Drag across a dense plot area to zoom into that slice, and use Reset Zoom to return to the full graph. JSON output returns the same point data for scripts or notebooks.

Each scatter point represents one person's text within one episode, with assistant and other-person transcript lines excluded before scoring. The implementation lives in the `tailwag_memory.inspect` package so the core memory service API remains focused on storage, retrieval, source adapters, and memory-item behavior. Future persisted affect scores should live on person-to-episode or person-to-memory relationships rather than on shared episode nodes.

The person timeline report combines read-only participation episodes and attended events into a browsable person view with hash links such as `#person=person_jamie`. The memory items report includes all stored memory items in the export scope, shows distributions by kind/status/source/person, and includes a follow-up state board for visible, not-yet-due, expired-active, addressed, and superseded follow-ups.

## Memory Maintenance

Backfill or debug memory extraction for a stored episode:

```bash
tailwag memory extract --episode-id episode_example_001
tailwag memory extract --episode-id episode_example_001 --person-id person_jamie
```

Consolidate repeated or related person memory evidence:

```bash
tailwag memory consolidate --person-id person_jamie
tailwag memory consolidate --all --person-limit 100
tailwag memory consolidate --person-id person_jamie --min-evidence-episodes 4 --seed-limit 25 --neighbor-limit 12 --cluster-limit 8
```

## Slack Polling

Slack polling has additional app-scope and state-file behavior. See [Slack Ingestion Guide](slack-ingestion.md#poll-commands) for setup and full polling details.

Common local commands:

```bash
tailwag slack poll --channel C0123456789 --once
tailwag slack poll --channel C0123456789 --once --backfill-hours 2
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill
tailwag slack poll --channel C0123456789 --once --backfill-hours 10 --force-backfill --skip-memory-extraction
tailwag slack poll --channel C0123456789 --interval 60
```

## Help

Every command exposes parser help:

```bash
tailwag --help
tailwag episode create --help
tailwag search --help
tailwag person context --help
tailwag memory consolidate --help
tailwag inspect affect --help
tailwag slack poll --help
```
