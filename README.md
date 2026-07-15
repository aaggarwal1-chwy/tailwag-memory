# tailwag-memory

Neo4j-only hybrid memory service with OpenAI-backed embeddings and deterministic/vector-derived person context.

## Documentation

The focused docs are the source of truth:

- [Architecture](docs/architecture.md): current scope, graph model, design boundaries, privacy/biometric boundaries, and deferred concepts.
- [Python package and caller integration guide](docs/integration-guide.md): package installation, runtime configuration, and HTTP integration for Argos or another caller.
- [Memory endpoints reference](docs/memory-endpoints.md): Python APIs, service constructors, input models, return shapes, and optional HTTP routes.
- [AWS deployment and operations](docs/aws-deployment.md): current live resources, private network topology, laptop Neo4j access, caller hookup, deployment workflow, verification, and known gaps.
- [AWS deployment resources](deploy/aws/README.md): local CloudFormation, IAM policy examples, image build/push helper, and worker packaging helper for AWS deployment.
- [AWS CI/CD](docs/aws-cicd.md): GitHub Actions validation and automatic dev deployment to existing AWS resources.
- [CLI reference](docs/cli-reference.md): local schema setup, ingestion, retrieval, memory maintenance, inspect, and Slack command examples.
- [Inspect reference](docs/inspect-reference.md): read-only report behavior, generated assets, filters, and affect report requirements.
- [Slack ingestion guide](docs/slack-ingestion.md): Slack app setup, polling, state handling, and inspection queries.
- [Repository agent instructions](AGENTS.md) and [agent trigger matrix](docs/agent-trigger-matrix.md): contributor agent workflow.

## Current Scope

Tailwag stores caller-owned people, places, episodes, events, directory rows, biometric references, and transcript-derived memory items in Neo4j. For implemented and deferred scope, see [Architecture](docs/architecture.md).

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
