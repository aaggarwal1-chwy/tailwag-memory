# Tailwag AWS Deployment Resources

This directory contains local deployment resources for running Tailwag in AWS.
The live service topology, resource inventory, access paths, and deployment
workflow are documented in
[`docs/aws-deployment.md`](../../docs/aws-deployment.md).

## Files

- `cloudformation/tailwag-memory-core.yaml`: shared AWS resources for the Tailwag API image and background worker flow.
- `cloudformation/tailwag-memory-edge.yaml`: public HTTPS API Gateway and private VPC Link to the Tailwag ALB.
- `cloudformation/tailwag-memory-observability.yaml`: CloudWatch alarms, SNS email routing, and AWS Backup failure routing.
- `deployment.env.example`: shell environment values used by the helper script and AWS CLI examples.
- `iam/tailwag-api-execution-role-policy.example.json`: ECS execution-role policy example for resolving the task-definition Secrets Manager values.
- `iam/tailwag-api-task-policy.example.json`: ECS application task-role policy example for send-only access to the memory extraction queue.
- `iam/tailwag-scheduler-policy.example.json`: EventBridge Scheduler role policy example for sending jobs to SQS.
- `iam/tailwag-worker-policy.example.json`: Lambda worker policy example for queue, state, and report access.
- `scheduler/slack-poll-schedule.example.json`: EventBridge Scheduler payload for recurring Slack poll jobs.
- `scheduler/report-generate-schedule.example.json`: EventBridge Scheduler payload for daily report jobs.
- `scheduler/memory-consolidate-all-schedule.example.json`: EventBridge Scheduler payload for daily bounded memory consolidation.
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
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    ReportsBucketName=aaggarwal1-tailwag-reports-<account-id>-us-east-2
```

Use `ReportsBucketName=<globally-unique-bucket-name>` when the bucket name must
be fixed. Leave it unset to let CloudFormation generate a bucket name.

Worker Lambdas are disabled by default because the stack needs a packaged Lambda
artifact in S3 before those functions can be created. To package locally:

```bash
WORKER_RUNTIME=python3.12 WORKER_ARCHITECTURE=x86_64 deploy/aws/scripts/package-worker-zip.sh
```

Upload the printed zip path to S3, then pass the code location plus concrete
handler names and runtime secret references:

```bash
aws cloudformation deploy \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-core-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    ReportsBucketName=aaggarwal1-tailwag-reports-<account-id>-us-east-2 \
    CreateWorkerLambdas=true \
    WorkerCodeS3Bucket=<worker-code-bucket> \
    WorkerCodeS3Key=<worker-code-key> \
    WorkerSubnetIds=<private-subnet-id-1>,<private-subnet-id-2> \
    WorkerSecurityGroupIds=<worker-security-group-id> \
    PollWorkerHandler=tailwag_memory.aws.handlers.slack_poll_handler \
    MemoryWorkerHandler=tailwag_memory.aws.handlers.memory_worker_handler \
    ReportWorkerHandler=tailwag_memory.aws.handlers.report_worker_handler \
    Neo4jUriSecretId=aaggarwal1-tailwag/neo4j-uri \
    Neo4jUserSecretId=aaggarwal1-tailwag/neo4j-user \
    Neo4jPasswordSecretId=aaggarwal1-tailwag/neo4j-password \
    OpenAIApiKeySecretId=aaggarwal1-tailwag/openai-api-key \
    SlackBotTokenSecretId=aaggarwal1-tailwag/slack-bot-token \
    TailwagApiBearerTokenSecretId=aaggarwal1-tailwag/api-bearer-token
```

The worker Lambda environment includes queue URLs, DynamoDB table names, the
reports bucket name, log level, worker kind, and the runtime variables expected
by Tailwag settings: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`OPENAI_API_KEY`, `SLACK_BOT_TOKEN`, and `TAILWAG_API_BEARER_TOKEN`.
CloudFormation populates those runtime variables through Secrets Manager dynamic
references.

The packaging helper requires Docker and builds inside the selected Lambda runtime and Linux architecture; set `WORKER_RUNTIME` and `WORKER_ARCHITECTURE` to match the CloudFormation worker parameters.

When Neo4j runs on a private EC2 address, pass `WorkerSubnetIds` and
`WorkerSecurityGroupIds` so worker Lambdas can reach Bolt. The selected worker
subnets need outbound access to AWS APIs, Slack, and OpenAI, typically through a
NAT gateway for the Lambda runtime.

The examples use one Secrets Manager namespace for all Tailwag runtime secrets:

- `aaggarwal1-tailwag/neo4j-uri`
- `aaggarwal1-tailwag/neo4j-user`
- `aaggarwal1-tailwag/neo4j-password`
- `aaggarwal1-tailwag/openai-api-key`
- `aaggarwal1-tailwag/slack-bot-token`
- `aaggarwal1-tailwag/api-bearer-token`

## Edge Stack

The edge stack creates an API Gateway HTTP API, a VPC Link to the existing
private ALB listener, a dedicated security group, ALB ingress from that security
group, and metadata-only access logs. API Gateway performs no authorization;
Tailwag continues to validate the existing bearer token.

Deploy the live development edge with:

```bash
aws cloudformation deploy \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-edge-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-edge.yaml \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    VpcId=vpc-00914e14c0001c9d8 \
    VpcLinkSubnetIds=subnet-00f10aeac0f8d4ad5,subnet-04c5d8d8ca431dc7f \
    AlbListenerArn=arn:aws:elasticloadbalancing:us-east-2:032318240470:listener/app/aaggarwal1-tailwag-alb/0a2bc296c3d68f79/93a7f8faa0d7950f \
    AlbSecurityGroupId=sg-0cd8c5bc8a094c8ef \
  --tags \
    awsApplication=arn:aws:resource-groups:us-east-2:032318240470:group/aaggarwal1-tailwag-dev/04671zpuoetw1clhbngkthqih7 \
    Project=aaggarwal1-tailwag \
    Environment=dev \
    chewy:environment=dev \
    chewy:owner_email=dl-robotics@chewy.com \
    chewy:cost_center=demm \
    chewy:app_name=physical_ai_robotics \
    chewy:data_classification=internal
```

Associate the edge stack with the existing AWS Application using
`APPLY_APPLICATION_TAG`, matching the core stack. Do not create a second
application:

```bash
EDGE_STACK_ARN="$(aws cloudformation describe-stacks \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-edge-dev \
  --query 'Stacks[0].StackId' \
  --output text)"

aws servicecatalog-appregistry associate-resource \
  --region us-east-2 \
  --application 04671zpuoetw1clhbngkthqih7 \
  --resource "$EDGE_STACK_ARN" \
  --resource-type CFN_STACK \
  --options APPLY_APPLICATION_TAG
```

The stack output `PublicApiEndpoint` is the caller base URL. The generated
`execute-api` URL stays stable for normal stack updates, but changes if the
API resource or entire stack is replaced.

AppRegistry lists the edge stack and supported tagged resources such as the
HTTP API, log group, and security group. `AWS::ApiGatewayV2::VpcLink` is not a
supported standalone AppRegistry resource-group type; it remains managed and
accounted for as a resource of the associated edge stack.

## Observability Stack

The observability stack creates 17 alarms covering API Gateway 5xx
and latency, ALB unhealthy targets, Lambda worker errors and throttles, SQS
queue age and DLQ messages, and Neo4j EC2 status checks and sustained CPU. It
also creates an SNS alarm topic, an email subscription, and an EventBridge rule
that routes failed, aborted, or expired AWS Backup jobs to the topic.

Deploy it only after discovering the live API, load balancer, target group,
Neo4j instance, AWS Application tag, and intended notification email. The email
recipient must confirm the subscription before notifications are delivered.

```bash
aws cloudformation deploy \
  --region us-east-2 \
  --stack-name aaggarwal1-tailwag-observability-dev \
  --template-file deploy/aws/cloudformation/tailwag-memory-observability.yaml \
  --parameter-overrides \
    ProjectName=aaggarwal1-tailwag \
    EnvironmentName=dev \
    ApplicationTagValue=<aws-application-resource-group-arn> \
    AlarmEmail=<alarm-email> \
    ApiGatewayId=<http-api-id> \
    LoadBalancerFullName=<app/name/id> \
    TargetGroupFullName=<targetgroup/name/id> \
    Neo4jInstanceId=<instance-id> \
  --tags \
    awsApplication=<aws-application-resource-group-arn> \
    Project=aaggarwal1-tailwag \
    Environment=dev \
    chewy:environment=dev \
    chewy:owner_email=dl-robotics@chewy.com \
    chewy:cost_center=demm \
    chewy:app_name=physical_ai_robotics \
    chewy:data_classification=internal
```

CloudFormation stack tags associate supported resources with the existing AWS
Application. The template also applies `awsApplication` directly to every
taggable alarm and routing resource. The SNS subscription and topic policy do
not support independent tags and are represented through their tagged topic
and stack.

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
entrypoint. External callers use API Gateway; traffic then crosses the VPC Link
and private ALB to the ECS service.

The SQS, DynamoDB, and S3 resources are the AWS-side dependencies for background
workers. Worker entrypoints should use:

- SQS for poll, memory extraction, consolidation, and report jobs
- DynamoDB for Slack poll cursor state and job idempotency
- S3 for generated report HTML and static assets
- Secrets Manager for Neo4j, OpenAI, Slack, and API tokens

Attach `iam/tailwag-api-execution-role-policy.example.json` to the `executionRoleArn` role and `iam/tailwag-api-task-policy.example.json` to the `taskRoleArn` role in the ECS task definition.

EventBridge Scheduler uses the application schedule group for Slack polling,
daily report generation, and daily memory consolidation. The examples cover all three job types, including `memory_consolidate_all` for the memory worker. The JSON examples in
`scheduler/` cover Slack, report, and bounded memory-consolidation payloads. Replace channel IDs,
ARNs, schedule expressions, and job payload fields before creating schedules.

## Updating The Deployed Application

Repository changes are deployed by an authenticated operator. Follow
[`docs/aws-manual-updates.md`](../../docs/aws-manual-updates.md) for API image,
worker package, verification, and rollback commands. Normal application updates
reuse the existing core and edge stacks; they do not recreate API Gateway, the
VPC Link, ALB, or Neo4j.
