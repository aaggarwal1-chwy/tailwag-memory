# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and deterministic/vector-derived person context.

## Documentation

The focused docs are the source of truth:

- [Architecture](docs/architecture.md): runtime scope, graph model, design boundaries, and privacy/biometric boundaries.
- [Python package and caller integration guide](docs/integration-guide.md): package installation, runtime configuration, and HTTP integration for Argos or another caller.
- [Memory endpoints reference](docs/memory-endpoints.md): Python APIs, service constructors, input models, return shapes, and optional HTTP routes.
- [AWS deployment and operations](docs/aws-deployment.md): live resources, private network topology, laptop Neo4j access, caller hookup, deployment workflow, verification, and deployment constraints.
- [AWS deployment resources](deploy/aws/README.md): local CloudFormation, IAM policy examples, image build/push helper, and worker packaging helper for AWS deployment.
- [AWS manual updates](docs/aws-manual-updates.md): operator-run API, worker, and infrastructure update procedures with verification and rollback.
- [Robot provenance and BOS3 migration](docs/robot-provenance-bos3-migration.md): local rehearsal, guarded Cypher transaction, coordinated AWS and Argos rollout, verification, and rollback.
- [CLI reference](docs/cli-reference.md): local schema setup, ingestion, retrieval, memory maintenance, inspect, and Slack command examples.
- [Inspect reference](docs/inspect-reference.md): read-only report behavior, generated assets, filters, and affect report requirements.
- [Slack ingestion guide](docs/slack-ingestion.md): Slack app setup, polling, state handling, and inspection queries.
- [Robot message relay](docs/message-relay.md): canonical-email identity, confirmation and permission gates, permanent body retention, local tests, and AWS rollout.
- [Repository agent instructions](AGENTS.md) and [agent trigger matrix](docs/agent-trigger-matrix.md): contributor agent workflow.

## Current Scope

Tailwag stores caller-owned people, narrow robot identities and episode provenance, places, episodes, events, directory rows, biometric references, transcript-derived memory items, and permission-gated `RelayMessage` records in Neo4j. Robot storage is intentionally limited to a stable ID, current display name, and per-episode name/role/source provenance; capabilities, sensors, software, live state, maintenance, and fleet modeling remain outside Tailwag. For the complete runtime scope and explicit boundaries, see [Architecture](docs/architecture.md).

## Local Setup

Minimal local loop:

```bash
docker compose up -d
cp .env.example .env
python3 -m pip install -e .
tailwag schema init
```

For complete setup, environment variables, optional extras, HTTP serving, directory sync, and command examples, use the [Python package integration guide](docs/integration-guide.md) and [CLI reference](docs/cli-reference.md). The local environment template is [.env.example](.env.example).

## Tests

The base test suite can run without a live Neo4j instance:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

For optional API contract tests and runtime-specific verification, see the [Python package integration guide](docs/integration-guide.md) and [Memory endpoints reference](docs/memory-endpoints.md).

For message relay, the mock/unit suite is only the first verification gate.
Real Neo4j concurrency tests, an AWS development-environment smoke test, and a
real Ubuntu robot hardware/audio run are separate gates; see
[Robot message relay](docs/message-relay.md#verification-gates).
