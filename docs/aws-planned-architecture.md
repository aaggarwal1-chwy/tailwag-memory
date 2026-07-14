# AWS Planned Architecture

## Purpose

This document describes the planned AWS deployment shape for Tailwag and its
integration points with Argos. Deployment resources live under
[`deploy/aws`](../deploy/aws/), and the API container deployment details live in
[`docs/aws-ecs-deployment.md`](aws-ecs-deployment.md).

## Architecture

```text
                            +-----------------------------+
                            | Local Argos or Cloud Argos  |
                            | HTTP memory provider client |
                            +--------------+--------------+
                                           |
                                           | HTTPS + bearer token
                                           v
              +----------------------------+----------------------------+
              | Application Load Balancer                               |
              | public with allowlist, or private through VPN/tunnel     |
              +----------------------------+----------------------------+
                                           |
                                           v
              +----------------------------+----------------------------+
              | ECS Fargate: tailwag-memory-api                         |
              | FastAPI routes under /argos/providers/memory/...         |
              | Returns context_markdown for memory.person_context       |
              +----------------------------+----------------------------+
                                           |
                                           | Bolt
                                           v
              +----------------------------+----------------------------+
              | Neo4j on EC2 + EBS or managed Neo4j                     |
              | Tailwag graph, vectors, memory items, reports source     |
              +---------------------------------------------------------+

  Scheduled/background path

  +-----------------------+       +-----------------------+
  | EventBridge Scheduler | ----> | SQS poll/report jobs  |
  +-----------------------+       +-----------+-----------+
                                              |
                                              v
  +-----------------------+       +-----------+-----------+
  | Slack Web API         | <---- | Lambda poll worker    |
  +-----------------------+       | slack_poll_handler    |
                                  +-----------+-----------+
                                              |
                 +----------------------------+----------------------------+
                 |                                                         |
                 v                                                         v
  +--------------+---------------+                         +---------------+--------------+
  | DynamoDB Slack poll state    |                         | SQS memory jobs              |
  | channel cursor + version     |                         | extraction/consolidation     |
  +------------------------------+                         +---------------+--------------+
                                                                          |
                                                                          v
                                                           +--------------+---------------+
                                                           | Lambda memory worker         |
                                                           | memory_worker_handler        |
                                                           +--------------+---------------+
                                                                          |
                                                                          | Bolt
                                                                          v
                                                           +--------------+---------------+
                                                           | Neo4j                        |
                                                           +------------------------------+

  Report path

  +-----------------------+       +-----------------------+       +-----------------------+
  | SQS report jobs       | ----> | Lambda report worker  | ----> | S3 reports bucket     |
  +-----------------------+       | report_worker_handler |       | static HTML/assets     |
                                  +-----------------------+       +-----------+-----------+
                                                                              |
                                                                              v
                                                                  +-----------+-----------+
                                                                  | CloudFront or        |
                                                                  | presigned S3 links   |
                                                                  +----------------------+

  Shared support

  +-----------------------+       +-----------------------+       +-----------------------+
  | Secrets Manager       |       | DynamoDB idempotency  |       | CloudWatch Logs      |
  | Neo4j, OpenAI, Slack, |       | worker job status     |       | ECS and Lambda logs  |
  | Tailwag API token     |       +-----------------------+       +-----------------------+
  +-----------------------+
```

## Request Path

Argos calls the Tailwag API over HTTP. Tailwag serves the Argos-facing memory
provider routes from ECS Fargate and reads/writes Neo4j over the private network.
For local Argos calling cloud Tailwag, use either:

- an internet-facing HTTPS ALB with bearer auth and IP allowlisting
- a private ALB reached through VPN, Tailscale, WireGuard, or SSM tunneling

Neo4j is not exposed publicly.

## Background Path

EventBridge Scheduler sends recurring jobs to SQS. Lambda workers consume those
jobs and use Tailwag package services:

- `slack_poll_handler` polls Slack, records episodes, and can enqueue memory
  extraction jobs.
- `memory_worker_handler` runs durable memory extraction and consolidation.
- `report_worker_handler` renders inspect reports and writes static files to S3.

SQS DLQs retain failed jobs after retry exhaustion. DynamoDB stores Slack channel
poll cursors and job idempotency state.

## AWS Resources

The planned deployment uses:

- ECS Fargate for the Tailwag FastAPI service
- Application Load Balancer for HTTP access
- EC2 + EBS or managed Neo4j for graph persistence
- ECR for the Tailwag API container image
- Lambda for poll, memory, and report workers
- SQS plus DLQs for worker jobs
- DynamoDB for Slack poll state and job idempotency
- EventBridge Scheduler for recurring poll and report jobs
- S3 for generated report HTML and assets
- CloudFront or presigned S3 URLs for report access
- Secrets Manager for runtime secrets
- CloudWatch Logs for ECS and Lambda logs

The deployment examples use one Secrets Manager namespace for Tailwag runtime
secrets:

- `tailwag/neo4j-uri`
- `tailwag/neo4j-user`
- `tailwag/neo4j-password`
- `tailwag/openai-api-key`
- `tailwag/slack-bot-token`
- `tailwag/api-bearer-token`

## Repo Resources

- [`deploy/aws/cloudformation/tailwag-memory-core.yaml`](../deploy/aws/cloudformation/tailwag-memory-core.yaml): ECR, SQS, DLQs, DynamoDB, S3, log groups, and optional Lambda workers.
- [`deploy/ecs-task-definition.example.json`](../deploy/ecs-task-definition.example.json): ECS task definition example for the API service.
- [`deploy/aws/scripts/build-push-api-image.sh`](../deploy/aws/scripts/build-push-api-image.sh): API image build and push helper.
- [`deploy/aws/scripts/package-worker-zip.sh`](../deploy/aws/scripts/package-worker-zip.sh): Lambda worker zip packaging helper.
- [`deploy/aws/scheduler`](../deploy/aws/scheduler): EventBridge Scheduler job examples.
