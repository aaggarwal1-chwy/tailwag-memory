# AWS Deployment And Operations

## Purpose

This document is the source of truth for the deployed Tailwag development
environment in AWS. It records the live architecture, resource names, access
paths, deployment workflow, verification commands, and known production
hardening gaps.

The inventory was last verified on 2026-07-15 in AWS account `032318240470`,
region `us-east-2`. Never place secret values in this document or in source
control.

## Current Status

The functional development deployment is live:

- the core CloudFormation stack is `UPDATE_COMPLETE`
- the edge CloudFormation stack is `CREATE_COMPLETE`
- the public API Gateway health and authenticated provider paths are verified
- the ECS API service is active with one healthy Fargate task
- the internal Application Load Balancer has one healthy target
- Neo4j is running on a private EC2 instance with encrypted EBS storage
- all three Lambda workers are active on worker package `dev-005`
- SQS event source mappings are enabled
- Slack polling for channel `C0896C8CE83` is enabled every 30 minutes
- the daily report schedule is enabled for 10:00 UTC
- DynamoDB Slack checkpoint creation and recurring updates are verified
- API, memory worker, report worker, and Slack worker smoke tests passed
- DynamoDB point-in-time recovery is enabled with a 35-day window on both state tables
- 17 first-wave CloudWatch alarms are enabled and currently healthy
- AWS Backup failure events route to the Tailwag alarm topic
- the alarm email subscription is confirmed and active
- all resources are grouped under the AWS Application
  `aaggarwal1-tailwag-dev`

The environment has a public HTTPS entry point to a private development
backend. It is not a production-ready public service. See
[Known Gaps](#known-gaps).

## Architecture

```text
Caller such as Argos
  (ordinary outbound HTTPS)
        |
        | HTTPS + bearer token
        v
API Gateway HTTP API
        |
        | VPC Link, HTTP :80
        v
Internal ALB :80
        |
        v
ECS Fargate API :8000 ------------------+
        |                                |
        | Bolt :7687                     | Secrets Manager
        v                                |
Private Neo4j EC2 + encrypted EBS <------+
        ^
        |
Lambda poll, memory, and report workers in private subnets
        ^
        |
SQS poll / memory / report queues + DLQs
        ^
        |
EventBridge Scheduler
  - Slack every 30 minutes
  - reports daily at 10:00 UTC

Worker state and output:
  - DynamoDB: Slack channel cursor and job idempotency
  - S3: generated reports and versioned Lambda ZIPs
  - CloudWatch Logs: ECS and Lambda logs
```

The shared VPC is not owned by Tailwag. Tailwag owns only its application
resources and security groups inside that VPC.

## Live Resource Inventory

### Application and stack

| Resource | Value |
| --- | --- |
| AWS account | `032318240470` |
| Region | `us-east-2` |
| AWS Application | `aaggarwal1-tailwag-dev` |
| Core CloudFormation stack | `aaggarwal1-tailwag-core-dev` |
| Edge CloudFormation stack | `aaggarwal1-tailwag-edge-dev` |
| Resource prefix | `aaggarwal1-tailwag` |
| Environment | `dev` |

Resources carry the `awsApplication` tag for the Tailwag application. The
shared VPC and shared subnets intentionally do not.

`AWS::ApiGatewayV2::VpcLink` is not a supported standalone AppRegistry
resource-group type, so it is represented through the associated edge stack.

### Network

| Resource | Value |
| --- | --- |
| Shared VPC | `vpc-00914e14c0001c9d8` (`physical_ai_robotics-vpc-dev`) |
| VPC CIDR | `10.107.67.0/24` |
| Private subnet, `us-east-2a` | `subnet-00f10aeac0f8d4ad5` |
| Private subnet, `us-east-2b` | `subnet-04c5d8d8ca431dc7f` |
| Private subnet, `us-east-2c` | `subnet-0ba5e9930bd4e3815` |
| ALB security group | `sg-0cd8c5bc8a094c8ef` |
| API Gateway VPC Link security group | `sg-03a4ec3efc17d1f02` |
| API security group | `sg-09d7a300548c72ac6` |
| Worker security group | `sg-0c8c107cc03cec6c4` |
| Neo4j security group | `sg-026c58f7ac8c20938` |

The internal ALB accepts HTTP from the approved VPC CIDR and the API Gateway
VPC Link security group. The VPC Link security group sends TCP `80` only to
the ALB security group. The API security group accepts port `8000` only from
the ALB security group. Neo4j accepts Bolt `7687` only from the API and worker
security groups. Neo4j Browser is not publicly exposed.

### API

| Resource | Value |
| --- | --- |
| ECS cluster | `aaggarwal1-tailwag-cluster` |
| ECS service | `aaggarwal1-tailwag-api-service` |
| Task family | `aaggarwal1-tailwag-api-task` |
| ECR repository | `aaggarwal1-tailwag-dev-api` |
| Deployed image tag | `dev-001` |
| Internal ALB | `aaggarwal1-tailwag-alb` |
| Target group | `aaggarwal1-tailwag-api-tg` |
| API Gateway HTTP API | `a9vhnyd929` |
| API Gateway VPC Link | `dg0r0q` |
| Container port | `8000` |
| Health path | `/health` |

The normal caller base URL is:

```text
https://a9vhnyd929.execute-api.us-east-2.amazonaws.com
```

The private backend URL is:

```text
http://internal-aaggarwal1-tailwag-alb-1363405968.us-east-2.elb.amazonaws.com
```

External callers should not use the private backend URL. API Gateway preserves
the request path and forwards the `Authorization` header to Tailwag through
the VPC Link.

### Neo4j

| Resource | Value |
| --- | --- |
| EC2 instance | `i-0ad802133b18b8655` |
| Instance name | `aaggarwal1-tailwag-neo4j` |
| Instance type | `t3.small` |
| Private IP | `10.107.67.7` |
| Data volume | `vol-08fc243d588cd2cd9` |
| Data volume size | 30 GiB, encrypted |
| Runtime | Neo4j 5 container on Ubuntu 24.04 |
| Private Bolt URI | `bolt://10.107.67.7:7687` |

The constraints and vector indexes are initialized for episodes, memory items,
face references, and voice references.

### Workers and schedules

| Resource | Value |
| --- | --- |
| Poll Lambda | `aaggarwal1-tailwag-dev-poll-worker` |
| Memory Lambda | `aaggarwal1-tailwag-dev-memory-worker` |
| Report Lambda | `aaggarwal1-tailwag-dev-report-worker` |
| Deployed worker object | `lambda/tailwag-memory-worker-dev-005.zip` |
| Schedule group | `aaggarwal1-tailwag-dev` |
| Slack schedule | `aaggarwal1-tailwag-dev-slack-poll-C0896C8CE83` |
| Slack cadence | `rate(30 minutes)` |
| Report schedule | `aaggarwal1-tailwag-dev-daily-report` |
| Report cadence | `cron(0 10 * * ? *)`, UTC |

Scheduler payloads include `<aws.scheduler.execution-id>` in `job_id`, so each
execution has a unique idempotency key. A superseded daily report schedule with
the same name remains disabled in the default schedule group; the enabled copy
is in the application schedule group.

### Queues, state, and storage

- SQS queues:
  - `aaggarwal1-tailwag-dev-poll-jobs`
  - `aaggarwal1-tailwag-dev-memory-jobs`
  - `aaggarwal1-tailwag-dev-report-jobs`
- DLQs use the same names with `-dlq` appended.
- DynamoDB tables:
  - `aaggarwal1-tailwag-dev-slack-poll-state`
  - `aaggarwal1-tailwag-dev-job-idempotency`
- S3 buckets:
  - `aaggarwal1-tailwag-reports-032318240470-us-east-2`
  - `aaggarwal1-tailwag-worker-code-032318240470-us-east-2`

The reports bucket is private. The worker-code bucket contains immutable ZIPs
such as `dev-001` through `dev-005`; only the object selected by the
CloudFormation `WorkerCodeS3Key` parameter runs. Older objects are rollback
artifacts, not additional environments or Lambda fleets.

### Secrets

Runtime values are stored in Secrets Manager under:

- `aaggarwal1-tailwag/neo4j-uri`
- `aaggarwal1-tailwag/neo4j-user`
- `aaggarwal1-tailwag/neo4j-password`
- `aaggarwal1-tailwag/openai-api-key`
- `aaggarwal1-tailwag/slack-bot-token`
- `aaggarwal1-tailwag/api-bearer-token`

The Neo4j password is the value originally supplied through the repository
`.env`. Secret values must never be committed, copied into documentation, or
placed directly in shell history when a safer retrieval mechanism is available.

### Observability

| Resource | Value |
| --- | --- |
| CloudFormation stack | `aaggarwal1-tailwag-observability-dev` |
| SNS topic | `aaggarwal1-tailwag-dev-alarms` |
| Alarm count | 17 |
| Backup failure rule | `aaggarwal1-tailwag-dev-backup-job-failure` |

The first-wave alarms cover API Gateway 5xx responses and p95 integration
latency, ALB unhealthy targets, errors and throttles for each Lambda worker,
oldest-message age and DLQ visibility for each SQS flow, and Neo4j EC2 status
checks and sustained CPU. Alarm and recovery notifications use the same SNS
topic. The backup rule reports failed, aborted, or expired AWS Backup jobs; it
does not itself create a backup plan.

The stack, all 17 alarms, the SNS topic, and the EventBridge rule carry the
existing `awsApplication` tag. The email subscription and topic policy are not
independently taggable and are represented through the tagged topic and stack.

## View Reports In S3

Generated reports are stored in the private reports bucket in `us-east-2`.
The operator needs AWS CLI credentials for account `032318240470` and read
access to the bucket. Verify the active identity, then list the available
report prefixes and files:

```bash
aws sts get-caller-identity --query "{Account:Account,Arn:Arn}" --output json

aws s3 ls \
  s3://aaggarwal1-tailwag-reports-032318240470-us-east-2/ \
  --recursive \
  --region us-east-2
```

Choose a prefix from that listing. For example, download the
`manual-smoke-002` report and its shared browser assets with:

```bash
REPORT_PREFIX=manual-smoke-002
mkdir -p "/tmp/tailwag-report/${REPORT_PREFIX}"

aws s3 cp \
  "s3://aaggarwal1-tailwag-reports-032318240470-us-east-2/${REPORT_PREFIX}/" \
  "/tmp/tailwag-report/${REPORT_PREFIX}/" \
  --recursive \
  --region us-east-2
```

Download the whole prefix rather than only one HTML object. The report pages
load `tailwag-inspect.css` and `tailwag-inspect.js` from the same directory.

Open a downloaded HTML file directly, or serve the directory locally:

```bash
python3 -m http.server 8000 \
  --directory "/tmp/tailwag-report/${REPORT_PREFIX}"
```

Keep that process running and browse to the report that exists in the prefix,
for example:

```text
http://localhost:8000/tailwag-memory-items.html
http://localhost:8000/tailwag-person-timeline.html
http://localhost:8000/tailwag-followup-validity.html
```

Only report types requested by the corresponding report job will be present.
The bucket can also be browsed in the AWS S3 console, but downloading the full
prefix is the reliable way to preserve the relative report asset links.

## Connect To Neo4j From A Laptop

Neo4j is private by design. Use AWS Systems Manager port forwarding; do not add
public security-group rules for ports `7474` or `7687`.

### Prerequisites

The laptop needs:

- AWS CLI credentials for account `032318240470`
- access to `ssm:StartSession` for instance `i-0ad802133b18b8655`
- the AWS Session Manager plugin
- region `us-east-2`

Verify the identity first:

```bash
aws sts get-caller-identity
aws configure get region
```

### Open the Browser tunnel

In terminal 1:

```bash
aws ssm start-session \
  --region us-east-2 \
  --target i-0ad802133b18b8655 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7474"],"localPortNumber":["7474"]}'
```

Keep the session open and browse to:

```text
http://localhost:7474
```

### Open the Bolt tunnel

In terminal 2:

```bash
aws ssm start-session \
  --region us-east-2 \
  --target i-0ad802133b18b8655 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7687"],"localPortNumber":["7687"]}'
```

In Neo4j Browser, connect with:

```text
URI: bolt://localhost:7687
Username: neo4j
Password: value in aaggarwal1-tailwag/neo4j-password
```

An authorized operator can retrieve the password into the current terminal:

```bash
NEO4J_PASSWORD="$(aws secretsmanager get-secret-value \
  --region us-east-2 \
  --secret-id aaggarwal1-tailwag/neo4j-password \
  --query SecretString \
  --output text)"
```

Do not echo that variable or paste it into tickets, chat, or source files.

The Bolt tunnel can also be used by local Tailwag commands:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD
tailwag schema init
```

If local port `7474` or `7687` is occupied, choose a different
`localPortNumber` and use that port in the Browser connection.

## Connect A Caller Such As Argos

Callers should use the Tailwag HTTP API. They should not connect directly to
Neo4j or read the worker queues and DynamoDB tables.

### Network and credentials

The caller needs outbound HTTPS connectivity to the API Gateway endpoint. No
VPN, transit route, or Tailwag VPC access is required.

For an operator-only test of the private backend, a local port can still be
forwarded through the SSM-managed Neo4j host:

```bash
aws ssm start-session \
  --region us-east-2 \
  --target i-0ad802133b18b8655 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{
    "host":["internal-aaggarwal1-tailwag-alb-1363405968.us-east-2.elb.amazonaws.com"],
    "portNumber":["80"],
    "localPortNumber":["8080"]
  }'
```

Keep the session open and set `TAILWAG_BASE_URL=http://localhost:8080` only
for that backend test. Persistent callers should use API Gateway.

Give the caller these runtime values through its own secret/configuration
system:

```text
TAILWAG_BASE_URL=https://a9vhnyd929.execute-api.us-east-2.amazonaws.com
TAILWAG_BEARER_TOKEN=<value from aaggarwal1-tailwag/api-bearer-token>
```

Those names are recommended examples. If Argos uses different configuration
keys, map its keys to the same base URL and bearer token. Do not copy the bearer
token into Argos source control.

### Health checks

The load-balancer health route is unauthenticated:

```bash
curl -fsS "$TAILWAG_BASE_URL/health"
```

The provider health route verifies authentication:

```bash
curl -fsS \
  -H "Authorization: Bearer $TAILWAG_BEARER_TOKEN" \
  "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/health"
```

### Core caller operations

Request prompt-ready person context:

```bash
curl -fsS \
  -H "Authorization: Bearer $TAILWAG_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "person_id": "person_jamie",
    "current_text": "robot demo later today",
    "limit": 10,
    "memory_limit": 12,
    "recent_episode_limit": 5
  }' \
  "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/request/person_context"
```

The caller should consume the returned `context_markdown` as prompt context.

Record a conversation episode:

```bash
curl -fsS \
  -H "Authorization: Bearer $TAILWAG_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "episode": {
      "id": "argos:conversation:example-001",
      "episode_type": "conversation",
      "start_time": "2026-07-15T14:00:00+00:00",
      "end_time": "2026-07-15T14:03:00+00:00",
      "transcript": "Jamie: I prefer hands-on robot demos.",
      "retention_class": "standard",
      "place": {"building_code": "MAIN", "room_id": "101"},
      "participants": [
        {"id": "person_jamie", "role": "speaker", "source": "live_chat"}
      ]
    },
    "extract_memory": true
  }' \
  "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/request/episodes_record"
```

Search a person's semantic memory:

```bash
curl -fsS \
  -H "Authorization: Bearer $TAILWAG_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"robot demos","person_id":"person_jamie","limit":5}' \
  "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/request/semantic_search"
```

The semantic response has separate `episodes` and `memory_items` lists.

### Argos provider mapping

In an Argos-style memory provider:

| Argos responsibility | Tailwag operation |
| --- | --- |
| Build prompt context | `POST .../request/person_context`; use `context_markdown` |
| Persist a completed live transcript | `POST .../request/episodes_record` |
| Run a user-directed memory search | `POST .../request/semantic_search` |
| Create or update a known person | `POST .../request/people_upsert` |
| Archive a person | `POST .../request/people_archive` |
| Resolve identity/profile data | identity and profile routes in the endpoint reference |

Argos remains responsible for realtime turn ownership, robot/runtime identity,
raw audio/video/transcript production, face and speaker embedding generation,
retention decisions, and final prompt assembly. Tailwag owns durable memory,
retrieval, Slack ingestion, and Neo4j persistence.

Use stable caller-owned person and episode IDs. Treat Tailwag memory-item IDs as
opaque. Retry only with the same episode ID when the payload represents the
same logical episode.

### Argos robot rollout checklist

Use this checklist after the Argos API Gateway integration change is deployed
to the robot:

1. Inject the current value of Secrets Manager secret
   `aaggarwal1-tailwag/api-bearer-token` as
   `TAILWAG_API_BEARER_TOKEN` through the robot's approved runtime secret
   mechanism. Do not store it in a manifest, shell script, or repository.
2. From the robot, set the public base URL and run both health checks:

   ```bash
   export TAILWAG_BASE_URL=https://a9vhnyd929.execute-api.us-east-2.amazonaws.com

   curl -fsS "$TAILWAG_BASE_URL/health"

   curl -fsS \
     -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
     "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/health"
   ```

   Both commands must succeed. No VPN or Tailwag VPC route is required.
3. With explicit operator approval for live robot and audio activity, start the
   normal Argos profile:

   ```bash
   cd ~/argos-agent
   source setup_shell.sh
   python3 run_profile.py --profile static_interaction
   ```

4. Have one enrolled, recognized speaker hold a short conversation containing a
   distinctive, non-sensitive fact suitable for later search.
5. Confirm all of the following:

   - Argos receives that person's Tailwag context without authentication or
     timeout errors.
   - Tailwag records the completed conversation episode for the resolved person.
   - An authenticated `semantic_search` request can retrieve the episode.
   - API Gateway logs in `/aws/apigateway/aaggarwal1-tailwag-dev` and API logs
     in `/ecs/aaggarwal1-tailwag-api` show successful Tailwag events without
     bearer-token, request-body, or memory-content logging.

6. Only after those checks pass, mark the live Argos rollout gap in
   [Known Gaps](#known-gaps) complete.

If the gateway or hosted service is unavailable, stop the live runtime and rely
on Argos's existing memory-unavailable behavior while investigating. To roll
back the configuration, restore the prior memory-provider endpoint in all three
Argos manifests and restart Argos. Rolling back Argos or deleting the edge stack
does not modify Tailwag's Neo4j data.

Slack polling is already owned by the Tailwag EventBridge schedule. Argos
should not start a second Slack poller for channel `C0896C8CE83`.

For the complete route catalog and schemas, see
[Memory Endpoints Reference](memory-endpoints.md#optional-http-endpoints).

## Deploy Application Changes

Repository changes are deployed manually by an authenticated operator. The
complete command-by-command procedure is in
[AWS Manual Updates](aws-manual-updates.md). There is no repository-triggered
deployment.

### API changes

1. Run tests.
2. Build an immutable image tag, preferably the Git commit SHA.
3. Push the image to `aaggarwal1-tailwag-dev-api` in ECR.
4. Register a new `aaggarwal1-tailwag-api-task` revision.
5. Update `aaggarwal1-tailwag-api-service` to that revision.
6. Wait for ECS stability and a healthy ALB target.
7. Run open and authenticated health checks plus an API smoke test.

The helper is [`deploy/aws/scripts/build-push-api-image.sh`](../deploy/aws/scripts/build-push-api-image.sh).

### Worker changes

1. Run the focused worker tests and full test suite.
2. Build the ZIP with
   [`deploy/aws/scripts/package-worker-zip.sh`](../deploy/aws/scripts/package-worker-zip.sh).
3. Upload it under a new immutable key such as
   `lambda/tailwag-memory-worker-dev-006.zip`.
4. Update `WorkerCodeS3Key` on `aaggarwal1-tailwag-core-dev` through
   CloudFormation.
5. Verify all Lambda updates and SQS mappings.
6. Run manual poll, memory, and report jobs before relying on schedules.

Do not overwrite the active S3 object in place. A versioned key preserves a
clear rollback target.

### Infrastructure changes

Use the CloudFormation template under `deploy/aws/cloudformation/` and preserve
the stack's `awsApplication`, project, environment, and governance tags. Review
a change set before applying replacement-prone or cost-increasing changes.
Associate every Tailwag stack with the existing `aaggarwal1-tailwag-dev`
application using `APPLY_APPLICATION_TAG`; do not create per-stack
applications.

### Schema changes

Schema initialization is idempotent. Run `tailwag schema init` from a network
path that can reach Neo4j, then verify the expected constraints and vector
indexes before deploying code that depends on them.

## Verification

Useful read-only checks:

```bash
aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --query 'Stacks[0].StackStatus'

aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-edge-dev \
  --query 'Stacks[0].{status:StackStatus,outputs:Outputs}'

aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-observability-dev \
  --query 'Stacks[0].{status:StackStatus,outputs:Outputs}'

aws cloudwatch describe-alarms \
  --region us-east-2 \
  --alarm-name-prefix aaggarwal1-tailwag-dev- \
  --query 'MetricAlarms[].{name:AlarmName,state:StateValue,actions:ActionsEnabled}'

aws ecs describe-services \
  --region us-east-2 \
  --cluster aaggarwal1-tailwag-cluster \
  --services aaggarwal1-tailwag-api-service \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'

aws scheduler get-schedule \
  --region us-east-2 \
  --group-name aaggarwal1-tailwag-dev \
  --name aaggarwal1-tailwag-dev-slack-poll-C0896C8CE83 \
  --query '{state:State,expression:ScheduleExpression}'
```

Check CloudWatch log groups:

- `/ecs/aaggarwal1-tailwag-api`
- `/aws/lambda/aaggarwal1-tailwag-dev-poll-worker`
- `/aws/lambda/aaggarwal1-tailwag-dev-memory-worker`
- `/aws/lambda/aaggarwal1-tailwag-dev-report-worker`
- `/aws/apigateway/aaggarwal1-tailwag-dev`

Any visible message in a DLQ requires investigation before replay.

## Secret Rotation

For a Neo4j password rotation:

1. change the password inside Neo4j
2. update `aaggarwal1-tailwag/neo4j-password` to the identical value
3. redeploy/restart the ECS task and Lambda workers
4. run API and worker connectivity checks
5. update authorized local `.env` files if they still need direct access

The rotation changes authentication only; it does not alter graph data,
indexes, EBS data, Slack state, or reports. An uncoordinated rotation causes
new API and Lambda Neo4j connections to fail until both sides agree.

Rotate the API bearer token by updating
`aaggarwal1-tailwag/api-bearer-token`, restarting the ECS API task, updating
the caller's secret, and rerunning provider health. Plan the ordering to avoid
an avoidable outage.

## Known Gaps

The deployed development environment does not yet have:

- HTTPS on the internal ALB
- automated Neo4j EBS backups, intentionally deferred because of recovery-point cost
- Neo4j disk and memory alarms from the CloudWatch Agent
- an authenticated synthetic check that proves live Neo4j connectivity
- a completed live robot Argos conversation and memory-retrieval rollout test

These are production-hardening or external-integration tasks, not missing core
AWS runtime components. Broad network exposure, credential rotation, resource
replacement, or materially cost-increasing changes require explicit approval.

## Repository Deployment Resources

- [`deploy/aws/cloudformation/tailwag-memory-core.yaml`](../deploy/aws/cloudformation/tailwag-memory-core.yaml)
- [`deploy/aws/cloudformation/tailwag-memory-edge.yaml`](../deploy/aws/cloudformation/tailwag-memory-edge.yaml)
- [`deploy/aws/cloudformation/tailwag-memory-observability.yaml`](../deploy/aws/cloudformation/tailwag-memory-observability.yaml)
- [`deploy/ecs-task-definition.example.json`](../deploy/ecs-task-definition.example.json)
- [`deploy/aws/scripts/build-push-api-image.sh`](../deploy/aws/scripts/build-push-api-image.sh)
- [`deploy/aws/scripts/package-worker-zip.sh`](../deploy/aws/scripts/package-worker-zip.sh)
- [`deploy/aws/scheduler`](../deploy/aws/scheduler)
- [`deploy/aws/iam`](../deploy/aws/iam)
