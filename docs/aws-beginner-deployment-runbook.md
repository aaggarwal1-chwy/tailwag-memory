# Beginner AWS Deployment Runbook

## Purpose

This runbook walks through a first Tailwag AWS deployment from a new or admin AWS
account. It is written for a console-first workflow, with CLI commands only
where the CLI is clearer or repeatable.

Use this from an Ubuntu deployment machine or an Ubuntu Codex instance.

## Fixed Choices

- AWS Region: `us-east-2` (Ohio)
- Resource prefix: `aaggarwal1-tailwag`
- Core stack: `aaggarwal1-tailwag-core-dev`
- API access: public HTTPS Application Load Balancer
- API runtime: ECS Fargate
- Graph database: Neo4j on EC2 with EBS
- Background workers: Lambda, SQS, DynamoDB, and S3
- Runtime secrets: Secrets Manager
- Argos hookup: after Tailwag standalone API and worker smoke tests pass

Template-managed resources created from `deploy/aws/cloudformation/tailwag-memory-core.yaml`
use both `ProjectName` and `EnvironmentName`. With this runbook's values, those
names use the form `aaggarwal1-tailwag-dev-<specific>`.

The core CloudFormation stack creates shared worker and storage resources. It
does not create the VPC, subnets, ECS cluster, ECS service, Application Load
Balancer, Neo4j EC2 instance, ECS task roles, or ECS service log group. This
runbook creates those resources separately through the AWS Console.

## Resource Names

Use these names unless an AWS service requires a globally unique suffix.

| Resource | Name |
| --- | --- |
| CloudFormation stack | `aaggarwal1-tailwag-core-dev` |
| ProjectName parameter | `aaggarwal1-tailwag` |
| EnvironmentName parameter | `dev` |
| ECR repository from core stack | `aaggarwal1-tailwag-dev-api` |
| ECS cluster | `aaggarwal1-tailwag-cluster` |
| ECS service | `aaggarwal1-tailwag-api-service` |
| ECS task family | `aaggarwal1-tailwag-api-task` |
| ALB | `aaggarwal1-tailwag-alb` |
| Target group | `aaggarwal1-tailwag-api-tg` |
| ALB security group | `aaggarwal1-tailwag-alb-sg` |
| ECS API security group | `aaggarwal1-tailwag-api-sg` |
| Lambda worker security group | `aaggarwal1-tailwag-worker-sg` |
| Neo4j security group | `aaggarwal1-tailwag-neo4j-sg` |
| Neo4j EC2 instance | `aaggarwal1-tailwag-neo4j` |
| Neo4j EBS volume | `aaggarwal1-tailwag-neo4j-data` |
| S3 reports bucket | `aaggarwal1-tailwag-reports-<account-id>-us-east-2` |
| S3 worker code bucket | `aaggarwal1-tailwag-worker-code-<account-id>-us-east-2` |
| Poll queue | `aaggarwal1-tailwag-dev-poll-jobs` |
| Poll DLQ | `aaggarwal1-tailwag-dev-poll-jobs-dlq` |
| Memory queue | `aaggarwal1-tailwag-dev-memory-jobs` |
| Memory DLQ | `aaggarwal1-tailwag-dev-memory-jobs-dlq` |
| Report queue | `aaggarwal1-tailwag-dev-report-jobs` |
| Report DLQ | `aaggarwal1-tailwag-dev-report-jobs-dlq` |
| Slack poll state table | `aaggarwal1-tailwag-dev-slack-poll-state` |
| Job idempotency table | `aaggarwal1-tailwag-dev-job-idempotency` |
| Poll worker Lambda | `aaggarwal1-tailwag-dev-poll-worker` |
| Memory worker Lambda | `aaggarwal1-tailwag-dev-memory-worker` |
| Report worker Lambda | `aaggarwal1-tailwag-dev-report-worker` |

Use these Secrets Manager names:

- `aaggarwal1-tailwag/neo4j-uri`
- `aaggarwal1-tailwag/neo4j-user`
- `aaggarwal1-tailwag/neo4j-password`
- `aaggarwal1-tailwag/openai-api-key`
- `aaggarwal1-tailwag/slack-bot-token`
- `aaggarwal1-tailwag/api-bearer-token`

## 1. AWS Account Setup

1. Sign in to the AWS Console.
2. In the region selector, choose **US East (Ohio) us-east-2**.
3. Open **Billing and Cost Management** and enable budget or billing alerts.
4. Confirm the account or role you use can create resources in:
   - IAM
   - CloudFormation
   - Secrets Manager
   - ECR
   - ECS
   - EC2
   - Elastic Load Balancing
   - Lambda
   - SQS
   - DynamoDB
   - S3
   - EventBridge Scheduler
   - CloudWatch

For a first personal deployment, an administrator role is the simplest starting
point. Tighten permissions after the deployment works.

## 2. Ubuntu Laptop Setup

Install required tools:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip zip unzip jq ca-certificates curl
```

Install Docker using Docker's current Ubuntu instructions:

https://docs.docker.com/engine/install/ubuntu/

Install AWS CLI v2 using AWS's current Linux instructions:

https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

Verify tools:

```bash
git --version
python3 --version
docker --version
aws --version
zip --version
```

Configure AWS CLI:

```bash
aws configure
```

Use:

- Default region name: `us-east-2`
- Default output format: `json`

Verify identity:

```bash
aws sts get-caller-identity
```

Clone or copy the repo onto Ubuntu, then from the repo root run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[api,aws]"
```

Run repo preflight checks:

```bash
.venv/bin/python -m unittest discover -s tests
python3 -m json.tool deploy/ecs-task-definition.example.json
python3 -m json.tool deploy/aws/iam/tailwag-api-task-policy.example.json
python3 -m json.tool deploy/aws/iam/tailwag-worker-policy.example.json
python3 -m json.tool deploy/aws/iam/tailwag-scheduler-policy.example.json
sh -n deploy/aws/scripts/build-push-api-image.sh
sh -n deploy/aws/scripts/package-worker-zip.sh
```

Expected result:

- Tests pass.
- JSON commands print formatted JSON and exit successfully.
- `sh -n` commands print no output.

## 3. Create Secrets

Open **AWS Console > Secrets Manager > Store a new secret**.

For each secret:

1. Choose **Other type of secret**.
2. Choose **Plaintext**.
3. Put only the raw value in the secret text box.
4. Name the secret exactly as listed.
5. Do not use JSON for these values.

Create:

| Secret | Value |
| --- | --- |
| `aaggarwal1-tailwag/neo4j-uri` | Temporary value such as `bolt://pending:7687`; update after Neo4j exists |
| `aaggarwal1-tailwag/neo4j-user` | Neo4j username, usually `neo4j` |
| `aaggarwal1-tailwag/neo4j-password` | Neo4j password |
| `aaggarwal1-tailwag/openai-api-key` | OpenAI API key |
| `aaggarwal1-tailwag/slack-bot-token` | Slack bot token |
| `aaggarwal1-tailwag/api-bearer-token` | Long random Tailwag API bearer token |

CLI verification:

```bash
aws secretsmanager list-secrets \
  --region us-east-2 \
  --query "SecretList[?starts_with(Name, 'aaggarwal1-tailwag/')].Name" \
  --output table
```

## 4. Deploy Core CloudFormation Stack

Open **AWS Console > CloudFormation > Stacks > Create stack > With new resources**.

Use:

- Template source: **Upload a template file**
- Template file: `deploy/aws/cloudformation/tailwag-memory-core.yaml`
- Stack name: `aaggarwal1-tailwag-core-dev`

Parameters:

| Parameter | Value |
| --- | --- |
| `ProjectName` | `aaggarwal1-tailwag` |
| `EnvironmentName` | `dev` |
| `ReportsBucketName` | `aaggarwal1-tailwag-reports-<account-id>-us-east-2` |
| `CreateWorkerLambdas` | `false` |

Leave worker code parameters empty for this first deploy.

This stack creates:

- ECR repository `aaggarwal1-tailwag-dev-api`
- SQS poll, memory, and report queues
- SQS DLQs for each worker queue
- DynamoDB Slack poll state table
- DynamoDB job idempotency table
- S3 reports bucket
- CloudWatch log groups for worker Lambdas
- Optional Lambda worker definitions when `CreateWorkerLambdas=true`

This stack does not create:

- VPC or subnets
- Neo4j EC2 or EBS
- ECS cluster or ECS service
- Application Load Balancer or target group
- ECS task execution role or ECS task role
- ECS API CloudWatch log group

On the final review page, acknowledge IAM creation if prompted, then create the
stack.

CLI equivalent:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

aws cloudformation deploy \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    ReportsBucketName="aaggarwal1-tailwag-reports-${ACCOUNT_ID}-us-east-2" \
    CreateWorkerLambdas=false
```

When the stack reaches `CREATE_COMPLETE`, open the **Outputs** tab and confirm:

- `ApiRepositoryUri`
- `PollJobsQueueUrl`
- `MemoryJobsQueueUrl`
- `ReportJobsQueueUrl`
- `SlackPollStateTableName`
- `JobIdempotencyTableName`
- `ReportsBucketName`

## 5. Provision Neo4j

### 5.1 Confirm worker network shape

The worker Lambdas must reach private Neo4j, AWS APIs, Slack, and OpenAI. Use
private subnets that have outbound internet through a NAT gateway. VPC endpoints
can reduce AWS API traffic, but Slack and OpenAI still require outbound internet
unless you add a separate proxy.

Record these values for Step 9:

- Private subnet ID 1: `subnet-...`
- Private subnet ID 2: `subnet-...`
- Worker security group ID: `sg-...`

Create or reserve these security groups:

| Security group | Inbound rules |
| --- | --- |
| `aaggarwal1-tailwag-alb-sg` | HTTP `80` or HTTPS `443` from your IP for first smoke test |
| `aaggarwal1-tailwag-api-sg` | TCP `8000` from `aaggarwal1-tailwag-alb-sg` |
| `aaggarwal1-tailwag-worker-sg` | No inbound rules required |
| `aaggarwal1-tailwag-neo4j-sg` | Bolt `7687` from `aaggarwal1-tailwag-api-sg` and `aaggarwal1-tailwag-worker-sg` |

Outbound rules can remain open for the first deployment. Tighten them after
smoke tests pass.

### 5.2 Create Neo4j EC2

Open **AWS Console > EC2 > Instances > Launch instance**.

Use:

- Name: `aaggarwal1-tailwag-neo4j`
- AMI: Ubuntu Server LTS
- Instance type: `t3.small` for a first dev deployment
- Network: same VPC that ECS will use
- Subnet: private subnet if available; otherwise restrict security groups tightly
- Storage: add an EBS volume for Neo4j data

Tag the data volume:

- Key: `Name`
- Value: `aaggarwal1-tailwag-neo4j-data`

Security group:

- Allow SSH `22` only from your IP if you use SSH.
- Prefer Session Manager instead of public SSH when available.
- Do not allow public Bolt access.
- Use `aaggarwal1-tailwag-neo4j-sg`.
- Allow Bolt `7687` only from `aaggarwal1-tailwag-api-sg` and
  `aaggarwal1-tailwag-worker-sg`.

On the Neo4j EC2 instance, install Docker and run Neo4j:

```bash
sudo mkdir -p /data/neo4j/data /data/neo4j/logs

sudo docker run -d \
  --name neo4j \
  --restart unless-stopped \
  -p 7474:7474 \
  -p 7687:7687 \
  -v /data/neo4j/data:/data \
  -v /data/neo4j/logs:/logs \
  -e NEO4J_AUTH="neo4j/<neo4j-password>" \
  neo4j:5
```

Replace `<neo4j-password>` with the same value stored in
`aaggarwal1-tailwag/neo4j-password`.

Find the EC2 instance private IP, then update the secret
`aaggarwal1-tailwag/neo4j-uri` to:

```text
bolt://<neo4j-private-ip>:7687
```

Run schema initialization from a machine that can reach the Neo4j private IP.
If your Ubuntu laptop is not connected to the VPC, use the Neo4j EC2 instance,
a temporary admin EC2 instance, VPN, or SSM port forwarding.

```bash
export NEO4J_URI="bolt://<neo4j-private-ip>:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="<neo4j-password>"
tailwag schema init
```

Expected result:

- Command exits successfully.
- Neo4j has Tailwag constraints and indexes.

## 6. Build And Push Tailwag API Image

On Ubuntu, create the deployment env file:

```bash
cp deploy/aws/deployment.env.example deploy/aws/deployment.env
```

Edit `deploy/aws/deployment.env`:

```bash
AWS_REGION=us-east-2
AWS_ACCOUNT_ID=<account-id>
PROJECT_NAME=aaggarwal1-tailwag
ENVIRONMENT_NAME=dev
ECR_REPOSITORY=aaggarwal1-tailwag-dev-api
IMAGE_TAG=dev-001
```

The checked-in `deployment.env.example` uses repo defaults. For this deployment,
replace those defaults with the values above before pushing an image.

Load the env file and push:

```bash
set -a
. deploy/aws/deployment.env
set +a
deploy/aws/scripts/build-push-api-image.sh
```

Copy the printed image URI. It should look like:

```text
<account-id>.dkr.ecr.us-east-2.amazonaws.com/aaggarwal1-tailwag-dev-api:dev-001
```

Open **AWS Console > ECR > Repositories > aaggarwal1-tailwag-dev-api** and
confirm the image exists.

## 7. Create ECS API Service And ALB

### 7.1 Create IAM roles

Open **AWS Console > IAM > Roles > Create role**.

Create ECS task execution role:

- Trusted entity: AWS service
- Service: Elastic Container Service
- Use case: Elastic Container Service Task
- Role name: `aaggarwal1-tailwag-ecs-execution-role`
- Attach managed policy: `AmazonECSTaskExecutionRolePolicy`
- Add inline permission for `secretsmanager:GetSecretValue` on:
  `arn:aws:secretsmanager:us-east-2:<account-id>:secret:aaggarwal1-tailwag/*`

Create ECS task role:

- Trusted entity: ECS task
- Role name: `aaggarwal1-tailwag-api-task-role`
- Attach inline policy from `deploy/aws/iam/tailwag-api-task-policy.example.json`,
  replacing `<region>` and `<account-id>`.

### 7.2 Create ECS cluster

Open **AWS Console > ECS > Clusters > Create cluster**.

Use:

- Cluster name: `aaggarwal1-tailwag-cluster`
- Infrastructure: AWS Fargate

### 7.3 Register task definition

Open **AWS Console > ECS > Task definitions > Create new task definition**.

Use:

- Task definition family: `aaggarwal1-tailwag-api-task`
- Launch type: AWS Fargate
- CPU: `0.5 vCPU`
- Memory: `1 GB`
- Task execution role: `aaggarwal1-tailwag-ecs-execution-role`
- Task role: `aaggarwal1-tailwag-api-task-role`
- Container name: `tailwag-memory-api`
- Image URI: image URI from Step 6
- Container port: `8000`
- Log group: `/ecs/aaggarwal1-tailwag-api`

Environment variables:

```text
TAILWAG_API_PORT=8000
TAILWAG_API_DOCS_ENABLED=false
TAILWAG_EMBEDDING_MODEL=text-embedding-3-small
TAILWAG_EMBEDDING_DIMENSION=64
TAILWAG_FACE_EMBEDDING_DIMENSION=512
TAILWAG_VOICE_EMBEDDING_DIMENSION=192
TAILWAG_FACE_EMBEDDING_MODEL=facenet
TAILWAG_VOICE_EMBEDDING_MODEL=speechbrain_ecapa
TAILWAG_SYNTHESIS_MODEL=gpt-5.5
```

Secrets:

| Env var | Secrets Manager secret |
| --- | --- |
| `NEO4J_URI` | `aaggarwal1-tailwag/neo4j-uri` |
| `NEO4J_USER` | `aaggarwal1-tailwag/neo4j-user` |
| `NEO4J_PASSWORD` | `aaggarwal1-tailwag/neo4j-password` |
| `OPENAI_API_KEY` | `aaggarwal1-tailwag/openai-api-key` |
| `TAILWAG_API_BEARER_TOKEN` | `aaggarwal1-tailwag/api-bearer-token` |

Health check command:

```text
CMD-SHELL, python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"
```

### 7.4 Create target group

Open **EC2 > Target Groups > Create target group**.

Use:

- Target type: IP addresses
- Name: `aaggarwal1-tailwag-api-tg`
- Protocol: HTTP
- Port: `8000`
- VPC: same VPC as ECS
- Health check path: `/health`

### 7.5 Create public ALB

Open **EC2 > Load Balancers > Create load balancer > Application Load Balancer**.

Use:

- Name: `aaggarwal1-tailwag-alb`
- Scheme: Internet-facing
- IP address type: IPv4
- Listener: HTTP `80` for first smoke test, or HTTPS `443` if an ACM certificate
  is ready
- VPC: same VPC as ECS
- Subnets: public subnets in at least two Availability Zones
- Security group: allow inbound `80` or `443` from your IP for first test
- Default action: forward to `aaggarwal1-tailwag-api-tg`

Use HTTPS before relying on the endpoint outside first smoke tests.

### 7.6 Create ECS service

Open **ECS > Clusters > aaggarwal1-tailwag-cluster > Services > Create**.

Use:

- Compute options: Launch type
- Launch type: Fargate
- Task definition: `aaggarwal1-tailwag-api-task`
- Service name: `aaggarwal1-tailwag-api-service`
- Desired tasks: `1`
- Networking: same VPC
- Subnets: private subnets when available
- Security group: allow inbound `8000` only from the ALB security group
- Load balancer: `aaggarwal1-tailwag-alb`
- Target group: `aaggarwal1-tailwag-api-tg`

After creation, wait for:

- ECS service deployment status is stable.
- Target group has one healthy target.

## 8. Smoke-Test API Without Argos

Find the ALB DNS name in **EC2 > Load Balancers**.

Set local variables:

```bash
export TAILWAG_ALB="http://<alb-dns-name>"
export TAILWAG_API_BEARER_TOKEN="<value from aaggarwal1-tailwag/api-bearer-token>"
```

Health check:

```bash
curl "$TAILWAG_ALB/health"
```

Expected response:

```json
{"status":"ok","service":"tailwag-memory"}
```

Authenticated provider health:

```bash
curl -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
  "$TAILWAG_ALB/argos/providers/memory/resources/memory/health"
```

Record one episode without memory extraction:

```bash
curl -X POST \
  -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  "$TAILWAG_ALB/argos/providers/memory/resources/memory/request/episodes_record" \
  -d '{
    "episode": {
      "id": "aws_smoke_episode_001",
      "episode_type": "conversation",
      "start_time": "2026-07-14T12:00:00+00:00",
      "end_time": "2026-07-14T12:02:00+00:00",
      "transcript": "Jamie: I am testing Tailwag on AWS.",
      "retention_class": "standard",
      "place": {"building_code": "AWS", "room_id": "smoke"},
      "participants": [{"id": "person_jamie", "display_name": "Jamie", "role": "speaker"}]
    },
    "extract_memory": false
  }'
```

Fetch person context:

```bash
curl -X POST \
  -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  "$TAILWAG_ALB/argos/providers/memory/resources/memory/request/person_context" \
  -d '{
    "person_id": "person_jamie",
    "current_text": "Tailwag AWS smoke test",
    "memory_limit": 12,
    "recent_episode_limit": 5
  }'
```

Expected result:

- Response contains `person_id`.
- Response contains `context_markdown`.
- ECS logs do not show startup or Neo4j connection failures.

## 9. Package And Enable Lambda Workers

Create the worker code bucket:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
WORKER_CODE_BUCKET="aaggarwal1-tailwag-worker-code-${ACCOUNT_ID}-us-east-2"

aws s3api create-bucket \
  --region us-east-2 \
  --bucket "$WORKER_CODE_BUCKET" \
  --create-bucket-configuration LocationConstraint=us-east-2
```

Build the worker zip:

```bash
deploy/aws/scripts/package-worker-zip.sh
```

Upload it:

```bash
aws s3 cp dist/tailwag-memory-worker.zip \
  "s3://${WORKER_CODE_BUCKET}/lambda/tailwag-memory-worker.zip" \
  --region us-east-2
```

Redeploy the core stack with workers enabled:

```bash
aws cloudformation deploy \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    ReportsBucketName="aaggarwal1-tailwag-reports-${ACCOUNT_ID}-us-east-2" \
    CreateWorkerLambdas=true \
    WorkerCodeS3Bucket="$WORKER_CODE_BUCKET" \
    WorkerCodeS3Key=lambda/tailwag-memory-worker.zip \
    WorkerSubnetIds="<private-subnet-id-1>,<private-subnet-id-2>" \
    WorkerSecurityGroupIds="<worker-security-group-id>" \
    Neo4jUriSecretId=aaggarwal1-tailwag/neo4j-uri \
    Neo4jUserSecretId=aaggarwal1-tailwag/neo4j-user \
    Neo4jPasswordSecretId=aaggarwal1-tailwag/neo4j-password \
    OpenAIApiKeySecretId=aaggarwal1-tailwag/openai-api-key \
    SlackBotTokenSecretId=aaggarwal1-tailwag/slack-bot-token \
    TailwagApiBearerTokenSecretId=aaggarwal1-tailwag/api-bearer-token
```

Confirm in **AWS Console > Lambda > Functions**:

- `aaggarwal1-tailwag-dev-poll-worker`
- `aaggarwal1-tailwag-dev-memory-worker`
- `aaggarwal1-tailwag-dev-report-worker`

Confirm each Lambda has an SQS trigger.

## 10. Manual Worker Tests

Get queue URLs:

```bash
POLL_QUEUE_URL="$(aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --query "Stacks[0].Outputs[?OutputKey=='PollJobsQueueUrl'].OutputValue" \
  --output text)"

MEMORY_QUEUE_URL="$(aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --query "Stacks[0].Outputs[?OutputKey=='MemoryJobsQueueUrl'].OutputValue" \
  --output text)"

REPORT_QUEUE_URL="$(aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --query "Stacks[0].Outputs[?OutputKey=='ReportJobsQueueUrl'].OutputValue" \
  --output text)"
```

Send a memory extraction job for the smoke episode:

```bash
aws sqs send-message \
  --region us-east-2 \
  --queue-url "$MEMORY_QUEUE_URL" \
  --message-body '{"job_type":"memory_extract_episode","job_id":"manual-extract-aws-smoke-001","episode_id":"aws_smoke_episode_001","person_id":"person_jamie"}'
```

Send a report job:

```bash
aws sqs send-message \
  --region us-east-2 \
  --queue-url "$REPORT_QUEUE_URL" \
  --message-body '{"job_type":"report_generate","job_id":"manual-report-aws-smoke-001","reports":["memory_items"],"output_prefix":"manual-smoke","limit":25}'
```

Send a Slack poll job only after the Slack bot is installed, invited to the
channel, and has the required scopes:

```bash
aws sqs send-message \
  --region us-east-2 \
  --queue-url "$POLL_QUEUE_URL" \
  --message-body '{"job_type":"slack_poll","job_id":"manual-slack-poll-001","channel":"C0123456789","history_limit":200,"reply_limit":200,"extract_memory":false}'
```

Verify:

```bash
aws sqs get-queue-attributes \
  --region us-east-2 \
  --queue-url "$MEMORY_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

Open **CloudWatch > Log groups** and inspect:

- `/aws/lambda/aaggarwal1-tailwag-dev-poll-worker`
- `/aws/lambda/aaggarwal1-tailwag-dev-memory-worker`
- `/aws/lambda/aaggarwal1-tailwag-dev-report-worker`

Open **SQS** and confirm DLQs remain empty:

- `aaggarwal1-tailwag-dev-poll-jobs-dlq`
- `aaggarwal1-tailwag-dev-memory-jobs-dlq`
- `aaggarwal1-tailwag-dev-report-jobs-dlq`

Open **DynamoDB** and confirm rows appear in:

- `aaggarwal1-tailwag-dev-job-idempotency`
- `aaggarwal1-tailwag-dev-slack-poll-state` after Slack polling

Open **S3** and confirm generated report objects appear in:

- `aaggarwal1-tailwag-reports-<account-id>-us-east-2`

## 11. Enable EventBridge Schedules

Create scheduler role in **IAM > Roles > Create role**:

- Trusted entity: AWS service
- Service: EventBridge Scheduler
- Role name: `aaggarwal1-tailwag-dev-scheduler-role`
- Inline policy: use `deploy/aws/iam/tailwag-scheduler-policy.example.json`,
  replacing queue ARNs with:
  - `arn:aws:sqs:us-east-2:<account-id>:aaggarwal1-tailwag-dev-poll-jobs`
  - `arn:aws:sqs:us-east-2:<account-id>:aaggarwal1-tailwag-dev-report-jobs`

Open **Amazon EventBridge > Scheduler > Create schedule**.

Create Slack poll schedule:

- Name: `aaggarwal1-tailwag-dev-slack-poll-C0123456789`
- Schedule pattern: rate-based
- Rate: start with `rate(15 minutes)`
- Target: SQS queue
- Queue: `aaggarwal1-tailwag-dev-poll-jobs`
- Role: `aaggarwal1-tailwag-dev-scheduler-role`
- Payload:

```json
{"job_type":"slack_poll","job_id":"slack-poll-C0123456789-scheduled","channel":"C0123456789","history_limit":200,"reply_limit":200,"extract_memory":false}
```

Create report schedule:

- Name: `aaggarwal1-tailwag-dev-daily-report`
- Schedule pattern: cron-based
- Cron: `cron(0 10 * * ? *)`
- Timezone: UTC
- Target: SQS queue
- Queue: `aaggarwal1-tailwag-dev-report-jobs`
- Role: `aaggarwal1-tailwag-dev-scheduler-role`
- Payload:

```json
{"job_type":"report_generate","job_id":"daily-report-scheduled","reports":["memory_items","person_timeline","followup_validity"],"output_prefix":"daily/"}
```

Keep schedules disabled until manual worker tests pass. Enable one schedule at a
time and check CloudWatch logs plus DLQs after the first run.

## 12. Hook Up Argos

Only start this after Tailwag standalone checks pass.

In Argos, configure:

- Tailwag base URL: ALB URL, preferably HTTPS
- Bearer token: value from `aaggarwal1-tailwag/api-bearer-token`

Argos should call:

```text
POST /argos/providers/memory/resources/memory/request/person_context
POST /argos/providers/memory/resources/memory/request/episodes_record
```

Expected contract:

- `person_context` returns `context_markdown`.
- Argos ingests the markdown directly.
- `episodes_record` can pass `extract_memory=false` when Argos wants async memory
  extraction handled outside the direct request path.

## 13. Production Readiness

Before relying on the deployment:

1. Replace HTTP ALB access with HTTPS using ACM.
2. Restrict ALB inbound access to known IPs where possible.
3. Confirm Neo4j Bolt `7687` is not public.
4. Add CloudWatch alarms for:
   - ECS unhealthy tasks
   - ECS task restarts
   - Lambda errors
   - SQS DLQ visible messages
   - Neo4j EC2 CPU
   - Neo4j disk usage
5. Configure EBS snapshots for the Neo4j data volume.
6. Confirm DynamoDB point-in-time recovery is enabled.
7. Confirm S3 versioning is enabled on the reports bucket.
8. Keep the last working ECS task definition revision.
9. Keep the previous Lambda zip in S3.
10. Rotate `aaggarwal1-tailwag/api-bearer-token` through Secrets Manager when
    changing API access.

## Troubleshooting

### CloudFormation stack fails

Open **CloudFormation > aaggarwal1-tailwag-core-dev > Events** and inspect the
first failed resource. Common causes:

- Reports bucket name is already taken.
- The deploying user lacks IAM permissions.
- Worker Lambda creation was enabled before uploading the worker zip.

### ECS task starts then stops

Open **ECS > Clusters > aaggarwal1-tailwag-cluster > Tasks > stopped task** and
read the stopped reason. Then open the CloudWatch log stream for the task.
Common causes:

- Bad Neo4j URI.
- ECS execution role cannot read Secrets Manager secrets.
- Neo4j security group does not allow ECS task access to Bolt `7687`.

### ALB target is unhealthy

Check:

- Target group health check path is `/health`.
- ECS security group allows inbound `8000` from the ALB security group.
- Container port is `8000`.
- Task logs show Uvicorn started successfully.

### Lambda worker fails

Open the worker log group in CloudWatch. Common causes:

- Worker cannot reach Neo4j.
- Worker role lacks SQS, DynamoDB, or S3 permissions.
- Secret name parameter points at the old `tailwag/...` namespace instead of
  `aaggarwal1-tailwag/...`.
- Slack bot token or channel access is not valid.

### Messages appear in a DLQ

Open the matching Lambda logs first. The DLQ confirms retry exhaustion; the logs
usually contain the root error. After fixing the cause, replay or resend the job
with a new `job_id`.

## External AWS References

- AWS CLI install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- Secrets Manager create secret: https://docs.aws.amazon.com/secretsmanager/latest/userguide/create_secret.html
- CloudFormation stack creation: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html
- ECR Docker push: https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html
- ECS Fargate getting started: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/getting-started-fargate.html
- Lambda with SQS: https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html
- EventBridge Scheduler: https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
