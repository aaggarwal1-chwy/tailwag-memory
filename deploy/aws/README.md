# Tailwag AWS Deployment Resources

This directory contains local deployment resources for running Tailwag in AWS.
The planned service topology is described in
[`docs/aws-planned-architecture.md`](../../docs/aws-planned-architecture.md).

## Files

- `cloudformation/tailwag-memory-core.yaml`: shared AWS resources for the Tailwag API image and background worker flow.
- `deployment.env.example`: shell environment values used by the helper script and AWS CLI examples.
- `iam/tailwag-api-task-policy.example.json`: ECS task policy example for the Tailwag API container.
- `iam/tailwag-scheduler-policy.example.json`: EventBridge Scheduler role policy example for sending jobs to SQS.
- `iam/tailwag-worker-policy.example.json`: Lambda worker policy example for queue, state, and report access.
- `scheduler/slack-poll-schedule.example.json`: EventBridge Scheduler payload for recurring Slack poll jobs.
- `scheduler/report-generate-schedule.example.json`: EventBridge Scheduler payload for daily report jobs.
- `scripts/build-push-api-image.sh`: builds the Tailwag API container and pushes it to ECR.
- `scripts/package-worker-zip.sh`: packages the Tailwag worker Lambda zip locally.
- `../ecs-task-definition.example.json`: ECS task definition example for the FastAPI container.

## Core Stack

The core CloudFormation stack creates:

- ECR repository for the Tailwag API image
- SQS poll, memory, and report queues
- DLQs for each SQS queue
- DynamoDB Slack poll state table
- DynamoDB job idempotency table
- S3 report bucket
- CloudWatch log groups for worker Lambdas
- Optional Lambda worker definitions and SQS event source mappings when worker
  code package parameters are supplied

Deploy it with:

```bash
aws cloudformation deploy \
  --stack-name tailwag-memory-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=tailwag-memory \
    EnvironmentName=dev
```

Use `ReportsBucketName=<globally-unique-bucket-name>` when the bucket name must
be fixed. Leave it unset to let CloudFormation generate a bucket name.

Worker Lambdas are disabled by default because the stack needs a packaged Lambda
artifact in S3 before those functions can be created. To package locally:

```bash
deploy/aws/scripts/package-worker-zip.sh
```

Upload the printed zip path to S3, then pass the code location plus concrete
handler names and runtime secret references:

```bash
aws cloudformation deploy \
  --stack-name tailwag-memory-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=tailwag-memory \
    EnvironmentName=dev \
    CreateWorkerLambdas=true \
    WorkerCodeS3Bucket=<worker-code-bucket> \
    WorkerCodeS3Key=<worker-code-key> \
    PollWorkerHandler=tailwag_memory.aws.handlers.slack_poll_handler \
    MemoryWorkerHandler=tailwag_memory.aws.handlers.memory_worker_handler \
    ReportWorkerHandler=tailwag_memory.aws.handlers.report_worker_handler \
    Neo4jUriSecretId=tailwag/neo4j-uri \
    Neo4jUserSecretId=tailwag/neo4j-user \
    Neo4jPasswordSecretId=tailwag/neo4j-password \
    OpenAIApiKeySecretId=tailwag/openai-api-key \
    SlackBotTokenSecretId=tailwag/slack-bot-token \
    TailwagApiBearerTokenSecretId=tailwag/api-bearer-token
```

The worker Lambda environment includes queue URLs, DynamoDB table names, the
reports bucket name, log level, worker kind, and the runtime variables expected
by Tailwag settings: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`OPENAI_API_KEY`, `SLACK_BOT_TOKEN`, and `TAILWAG_API_BEARER_TOKEN`.
CloudFormation populates those runtime variables through Secrets Manager dynamic
references.

The examples use one Secrets Manager namespace for all Tailwag runtime secrets:

- `tailwag/neo4j-uri`
- `tailwag/neo4j-user`
- `tailwag/neo4j-password`
- `tailwag/openai-api-key`
- `tailwag/slack-bot-token`
- `tailwag/api-bearer-token`

## Build And Push The API Image

Copy the example values and set the account, region, and tag:

```bash
cp deploy/aws/deployment.env.example deploy/aws/deployment.env
```

Then source the file and push the image:

```bash
set -a
. deploy/aws/deployment.env
set +a
deploy/aws/scripts/build-push-api-image.sh
```

The script creates the ECR repository when it is missing, logs Docker into ECR,
builds the local `Dockerfile`, tags the image, and pushes it.

## Runtime Wiring

The ECS API service uses the pushed image and the existing FastAPI container
entrypoint. Argos calls the Tailwag API through the ECS service or load balancer.

The SQS, DynamoDB, and S3 resources are the AWS-side dependencies for background
workers. Worker entrypoints should use:

- SQS for poll, memory extraction, consolidation, and report jobs
- DynamoDB for Slack poll cursor state and job idempotency
- S3 for generated report HTML and static assets
- Secrets Manager for Neo4j, OpenAI, Slack, and API tokens

EventBridge Scheduler can use the JSON examples in `scheduler/` to enqueue
recurring Slack poll jobs and daily report jobs. Replace channel IDs, ARNs,
schedule expressions, and job payload fields before creating schedules.
