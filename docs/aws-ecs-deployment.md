# AWS ECS Deployment

## Purpose

This note describes the Tailwag API container packaging for an ECS Fargate
deployment. Shared AWS resource templates and image push helpers live under
[`deploy/aws`](../deploy/aws/).
The full planned AWS topology is described in
[`docs/aws-planned-architecture.md`](aws-planned-architecture.md).

## Container Image

Build the API image from the repository root:

```bash
docker build -t tailwag-memory-api:local .
```

Run it locally against an existing Neo4j endpoint:

```bash
docker run --rm -p 8000:8000 \
  -e NEO4J_URI=bolt://host.docker.internal:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=tailwag-memory \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e TAILWAG_API_BEARER_TOKEN=dev-token \
  tailwag-memory-api:local
```

The image starts:

```bash
python -m uvicorn tailwag_memory.api.app:create_app --factory --host 0.0.0.0 --port ${TAILWAG_API_PORT:-8000}
```

`GET /health` is the unauthenticated container and load-balancer health route.
All Argos memory provider routes require `Authorization: Bearer
<TAILWAG_API_BEARER_TOKEN>`.

## ECS Shape

Use the image with:

- ECS Fargate service in private subnets
- internal Application Load Balancer
- container port `8000`
- ALB health check path `/health`
- task execution role for ECR, Secrets Manager, and
  CloudWatch logs
- task security group allowed to reach Neo4j Bolt
- Neo4j security group allowing Bolt only from Tailwag API tasks and approved
  worker tasks/functions

An example task definition lives at
[`deploy/ecs-task-definition.example.json`](../deploy/ecs-task-definition.example.json).
Replace account, region, image, role, and secret ARNs before registering it.

The core AWS resource template lives at
[`deploy/aws/cloudformation/tailwag-memory-core.yaml`](../deploy/aws/cloudformation/tailwag-memory-core.yaml).
It creates the ECR repository, SQS queues and DLQs, DynamoDB state tables, S3
report bucket, and worker log groups used by the deployment.

## Runtime Configuration

Store sensitive values in Secrets Manager:

- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `OPENAI_API_KEY`
- `TAILWAG_API_BEARER_TOKEN`

The deployment examples use these Secrets Manager secret IDs:

- `tailwag/neo4j-uri`
- `tailwag/neo4j-user`
- `tailwag/neo4j-password`
- `tailwag/openai-api-key`
- `tailwag/slack-bot-token`
- `tailwag/api-bearer-token`

Set non-sensitive values directly as ECS task environment variables:

- `TAILWAG_API_PORT=8000`
- `TAILWAG_API_DOCS_ENABLED=false`
- `TAILWAG_EMBEDDING_MODEL`
- `TAILWAG_EMBEDDING_DIMENSION`
- `TAILWAG_FACE_EMBEDDING_DIMENSION`
- `TAILWAG_VOICE_EMBEDDING_DIMENSION`
- `TAILWAG_FACE_EMBEDDING_MODEL`
- `TAILWAG_VOICE_EMBEDDING_MODEL`
- `TAILWAG_SYNTHESIS_MODEL`

Run Tailwag schema initialization once per Neo4j database before routing live
traffic to the service.

## Verification

After deployment:

```bash
curl http://<internal-alb-dns>/health
curl -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
  http://<internal-alb-dns>/argos/providers/memory/resources/memory/health
```

Then run an authenticated `person_context` request from the same network path
Argos will use. Argos should continue to call `memory.person_context` and
consume the returned `context_markdown` field directly.
