# AWS Manual Updates

## Purpose

Tailwag repository changes are deployed to the existing AWS development
application by an authenticated operator. There is no repository-triggered CI
or deployment workflow. These procedures preserve the existing API Gateway,
VPC Link, private ALB, ECS service, Neo4j instance, secrets, queues, tables, and
stored memory data.

Use an immutable Git commit SHA for every API image and worker package. Never
overwrite an active image tag or worker object in place.

## Prerequisites

Run commands from the Tailwag repository root. The operator workstation needs
Python 3, AWS CLI v2, Docker, `jq`, `zip`, and `curl`.

Authenticate using the normal AWS SSO flow. When a named profile is required:

```bash
aws sso login --profile <profile>
export AWS_PROFILE=<profile>
```

Set the stable resource names for the target environment. Use actual values
from the authorized AWS inventory; do not commit a populated deployment file.

```bash
export AWS_REGION=us-east-2
export CORE_STACK_NAME=<core-stack-name>
export EDGE_STACK_NAME=<edge-stack-name>
export ECR_REPOSITORY=<api-ecr-repository-name>
export ECS_CLUSTER=<ecs-cluster-name>
export ECS_SERVICE=<ecs-service-name>
export ECS_TASK_FAMILY=<ecs-task-family>
export ECS_CONTAINER_NAME=tailwag-memory-api
export TAILWAG_API_BEARER_TOKEN_SECRET_ID=<bearer-token-secret-id>

export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export IMAGE_TAG="$(git rev-parse HEAD)"
```

Before changing AWS, confirm that the identity, account, region, branch, and
commit are the intended deployment target:

```bash
aws sts get-caller-identity
git status --short
git log -1 --oneline
```

Do not deploy from a dirty worktree unless those exact local changes are the
intended release.

## Validate The Release

Install the API and AWS extras in an isolated environment, then run the local
checks relevant to the change. The full unit suite does not require live AWS or
Neo4j.

```bash
python3 -m pip install -e ".[api,aws]"
python3 -m pip check
PYTHONPATH=src python3 -m unittest discover -s tests

python3 -m json.tool deploy/ecs-task-definition.example.json >/dev/null
python3 -m json.tool deploy/aws/iam/tailwag-api-task-policy.example.json >/dev/null
python3 -m json.tool deploy/aws/iam/tailwag-scheduler-policy.example.json >/dev/null
python3 -m json.tool deploy/aws/iam/tailwag-worker-policy.example.json >/dev/null
python3 -m json.tool deploy/aws/scheduler/slack-poll-schedule.example.json >/dev/null
python3 -m json.tool deploy/aws/scheduler/report-generate-schedule.example.json >/dev/null

sh -n deploy/aws/scripts/build-push-api-image.sh
sh -n deploy/aws/scripts/package-worker-zip.sh

aws cloudformation validate-template \
  --region "$AWS_REGION" \
  --template-body file://deploy/aws/cloudformation/tailwag-memory-core.yaml \
  >/dev/null
```

Also run focused tests for the modules changed by the release. Stop if any
validation fails.

## Record Rollback Targets

Record the active ECS revision before an API deployment:

```bash
export PREVIOUS_TASK_DEFINITION_ARN="$(aws ecs describe-services \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --query 'services[0].taskDefinition' \
  --output text)"

printf 'Previous ECS task definition: %s\n' "$PREVIOUS_TASK_DEFINITION_ARN"
```

For workers, record the current `WorkerCodeS3Key` stack parameter:

```bash
export PREVIOUS_WORKER_CODE_S3_KEY="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$CORE_STACK_NAME" \
  --query "Stacks[0].Parameters[?ParameterKey=='WorkerCodeS3Key'].ParameterValue | [0]" \
  --output text)"

printf 'Previous worker object: %s\n' "$PREVIOUS_WORKER_CODE_S3_KEY"
```

Store these values in the operator's deployment notes, not in the repository.

## Deploy API Changes

Build and push the API image:

```bash
export PROJECT_NAME=<project-name>
export ENVIRONMENT_NAME=dev
export IMAGE_TAG="$(git rev-parse HEAD)"

export IMAGE_URI="$(deploy/aws/scripts/build-push-api-image.sh)"
printf 'Pushed image: %s\n' "$IMAGE_URI"
```

Render a new task definition from the currently deployed revision. This keeps
the existing roles, secrets, logging, health check, CPU, memory, and network
contract while changing only the selected container image.

```bash
aws ecs describe-task-definition \
  --region "$AWS_REGION" \
  --task-definition "$ECS_TASK_FAMILY" \
  --query taskDefinition \
  --output json \
| jq \
    --arg container "$ECS_CONTAINER_NAME" \
    --arg image "$IMAGE_URI" \
    'del(
       .taskDefinitionArn,
       .revision,
       .status,
       .requiresAttributes,
       .compatibilities,
       .registeredAt,
       .registeredBy
     )
     | .containerDefinitions |= map(
         if .name == $container then .image = $image else . end
       )' \
> /tmp/tailwag-task-definition.json

export NEW_TASK_DEFINITION_ARN="$(aws ecs register-task-definition \
  --region "$AWS_REGION" \
  --cli-input-json file:///tmp/tailwag-task-definition.json \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"

aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$NEW_TASK_DEFINITION_ARN" \
  --force-new-deployment \
  >/dev/null

aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE"
```

Delete `/tmp/tailwag-task-definition.json` after verification. Do not commit a
rendered task definition.

## Deploy Worker Changes

Package workers and upload the ZIP under an immutable key:

```bash
export WORKER_ZIP_PATH="$(deploy/aws/scripts/package-worker-zip.sh)"
export WORKER_CODE_S3_BUCKET="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$CORE_STACK_NAME" \
  --query "Stacks[0].Parameters[?ParameterKey=='WorkerCodeS3Bucket'].ParameterValue | [0]" \
  --output text)"
export WORKER_CODE_S3_KEY="lambda/$(git rev-parse HEAD)/tailwag-memory-worker.zip"

test -n "$WORKER_CODE_S3_BUCKET"
test "$WORKER_CODE_S3_BUCKET" != "None"

aws s3 cp \
  "$WORKER_ZIP_PATH" \
  "s3://${WORKER_CODE_S3_BUCKET}/${WORKER_CODE_S3_KEY}" \
  --region "$AWS_REGION"
```

Update the existing core stack. Parameters not listed in an update retain their
current stack values.

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$CORE_STACK_NAME" \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    CreateWorkerLambdas=true \
    WorkerCodeS3Bucket="$WORKER_CODE_S3_BUCKET" \
    WorkerCodeS3Key="$WORKER_CODE_S3_KEY"
```

A worker-code-only update reuses the existing IAM role and network settings.
If the template adds or changes IAM resources, the update can require an IAM
administrator even when ordinary worker deployments succeed.

## Infrastructure Changes

Use the templates under `deploy/aws/cloudformation/`. Create and review a
CloudFormation change set before executing replacement-prone, public-network,
IAM, or materially cost-increasing changes. Preserve the existing AWS
Application association and governance tags, and do not recreate the edge stack
for ordinary application updates.

The current PowerUser access may deploy application and worker changes but does
not grant unrestricted IAM administration. Stop if CloudFormation proposes an
unexpected replacement or reports an IAM authorization failure.

## Verify The Deployment

Confirm ECS converged on the new revision:

```bash
aws ecs describe-services \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount,task:taskDefinition,events:events[0:3]}'
```

Discover the public endpoint from the edge stack and run read-only health
checks. Retrieve the bearer token into the shell only; do not print it or place
it in a document or committed file.

```bash
export TAILWAG_BASE_URL="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$EDGE_STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='PublicApiEndpoint'].OutputValue | [0]" \
  --output text)"

curl -fsS "${TAILWAG_BASE_URL%/}/health"

export TAILWAG_API_BEARER_TOKEN="$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$TAILWAG_API_BEARER_TOKEN_SECRET_ID" \
  --query SecretString \
  --output text)"

curl -fsS \
  -H "Authorization: Bearer ${TAILWAG_API_BEARER_TOKEN}" \
  "${TAILWAG_BASE_URL%/}/argos/providers/memory/resources/memory/health"

unset TAILWAG_API_BEARER_TOKEN
```

For worker changes, confirm all Lambda functions report the expected
`LastUpdateStatus`, inspect recent CloudWatch logs, and verify SQS dead-letter
queues remain empty. Run write smoke jobs only when the operator explicitly
accepts changes to the development memory store or report bucket.

## Rollback

Roll back the API to the task definition recorded before deployment:

```bash
aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$PREVIOUS_TASK_DEFINITION_ARN" \
  --force-new-deployment \
  >/dev/null

aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE"
```

Roll back workers by redeploying the previously recorded immutable object key:

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$CORE_STACK_NAME" \
  --template-file deploy/aws/cloudformation/tailwag-memory-core.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    CreateWorkerLambdas=true \
    WorkerCodeS3Bucket="$WORKER_CODE_S3_BUCKET" \
    WorkerCodeS3Key="$PREVIOUS_WORKER_CODE_S3_KEY"
```

Rerun all read-only health and service checks after rollback. API and worker
rollback do not modify Neo4j identities, episodes, memories, or biometrics.
