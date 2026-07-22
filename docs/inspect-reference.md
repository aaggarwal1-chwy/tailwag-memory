# Inspect Reference

## Purpose

Tailwag inspect utilities are read-only developer/operator reports for local graph investigation. They export static HTML or JSON from existing Neo4j data and do not write schema changes, memory records, affect scores, or lifecycle updates back to Neo4j.

For command syntax in the broader local workflow, see [CLI Reference](cli-reference.md). For the normal package API, see [Memory Endpoints Reference](memory-endpoints.md).

## Report Family

The `tailwag inspect` command exposes four reports:

| Command | Default HTML output | Purpose |
| --- | --- | --- |
| `tailwag inspect followup-validity` | `inspect/tailwag-followup-validity.html` | Groups follow-up memories by active/addressed/superseded/invalid state and validity-window duration. |
| `tailwag inspect affect` | `inspect/tailwag-affect.html` | Scores person-specific episode transcript text for valence/arousal using external fold model directories. |
| `tailwag inspect person-timeline` | `inspect/tailwag-person-timeline.html` | Shows a read-only timeline of participation episodes and attended events by person. |
| `tailwag inspect memory-items` | `inspect/tailwag-memory-items.html` | Shows memory item distributions, evidence links, status, source, and follow-up state. |

The committed `inspect/index.html` and report pages can be opened as static browser entry points. Committed report pages should stay empty placeholders; generated reports may embed live graph data and should not be committed unless intentionally sanitized. Regenerating a report replaces that page's embedded report data and keeps the shared report navigation.

## Commands

Follow-up validity:

```bash
tailwag inspect followup-validity
tailwag inspect followup-validity --limit 250
tailwag inspect followup-validity --format json --output -
```

Affect scoring:

```bash
python3 -m pip install -e ".[affect]"
tailwag inspect affect --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
tailwag inspect affect --person-id person_jamie --limit 25 --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
tailwag inspect affect --format json --output - --fold1-model /path/to/fold1 --fold2-model /path/to/fold2
```

Person timeline:

```bash
tailwag inspect person-timeline
tailwag inspect person-timeline --person-id person_jamie
tailwag inspect person-timeline --person-id person_jamie --format json --output -
```

Memory items:

```bash
tailwag inspect memory-items
tailwag inspect memory-items --person-id person_jamie
tailwag inspect memory-items --person-id person_jamie --format json --output -
```

## Output Behavior

HTML is the default format. When `--output` is omitted for HTML, Tailwag writes the canonical report file under `inspect/`. When `--output path/to/report.html` is provided, Tailwag writes that report path instead.

HTML exports also write shared browser assets beside the report:

- `tailwag-inspect.css`
- `tailwag-inspect.js`

Use `--format json --output -` to print the same report envelope to stdout for scripts or notebooks. JSON output does not write browser assets.

## Navigation And Filters

Generated HTML reports share one navigation order:

1. Follow-Up Validity
2. Affect
3. Person Timeline
4. Memory Items

Reports preserve useful filters in hash links where possible, such as person, episode, memory, kind, status, source, follow-up state, and validity bucket. For example, the person timeline supports hash links such as `#person=person_jamie`, and related links can carry that person filter into memory or affect reports.

## Affect Requirements

Only `tailwag inspect affect` requires the optional affect dependency and external XLM-RoBERTa-large fold model directories. Provide those directories with CLI flags or environment-backed settings:

```bash
TAILWAG_AFFECT_FOLD1_MODEL=/path/to/fold1
TAILWAG_AFFECT_FOLD2_MODEL=/path/to/fold2
```

The affect report scores on demand. Each scatter point represents one person's text within one episode, with assistant and other-person transcript lines excluded before scoring. The plot displays valence and arousal on centered `-1..1` axes while keeping the model's native `0..1` averaged fold scores available in the detail panel. Points with same-person memory item evidence linked to the episode are highlighted and show the linked memory count.

## Boundaries

Inspection helpers are imported from `tailwag_memory.inspect`, not from the top-level package. They are intended for local analysis and report generation, not for normal memory-service integration.

The inspect package must remain read-only. It may query episodes, events, people, and memory items, but it should not own ingestion, schema expansion, memory extraction, consolidation, or lifecycle mutation.
