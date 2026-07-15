# AWS CI/CD

## Purpose

Tailwag uses GitHub Actions to validate pull requests and deploy the `main`
branch to the existing AWS dev environment. The pipeline automates repeat
deployments only: it builds and pushes the API image, uploads an immutable
worker zip, updates the core CloudFormation stack, registers a new ECS task
definition, and rolls the existing ECS service.

The first-time AWS environment setup and live resource inventory are documented
in [AWS Deployment And Operations](aws-deployment.md). In v1, CI/CD does not
create the VPC, subnets, ALB, ECS cluster, ECS service, Neo4j EC2 instance, ECS
task roles, EventBridge schedules, API Gateway edge stack, VPC Link, or
CloudWatch alarms.

## Verified live dev AWS configuration

The following values were verified on 2026-07-15. Use them when configuring the
GitHub `dev` environment; do not create a second Tailwag application or a
parallel set of dev resources.

| Resource | Live value |
| --- | --- |
| AWS account | `032318240470` |
| Region | `us-east-2` |
| AWS Application | `aaggarwal1-tailwag-dev` |
| Application ID | `04671zpuoetw1clhbngkthqih7` |
| Application tag | `awsApplication=arn:aws:resource-groups:us-east-2:032318240470:group/aaggarwal1-tailwag-dev/04671zpuoetw1clhbngkthqih7` |
| Core stack | `aaggarwal1-tailwag-core-dev` |
| Edge stack | `aaggarwal1-tailwag-edge-dev` |
| ECR repository | `aaggarwal1-tailwag-dev-api` |
| Worker artifact bucket | `aaggarwal1-tailwag-worker-code-032318240470-us-east-2` |
| Reports bucket | `aaggarwal1-tailwag-reports-032318240470-us-east-2` |
| ECS cluster | `aaggarwal1-tailwag-cluster` |
| ECS service | `aaggarwal1-tailwag-api-service` |
| ECS task family | `aaggarwal1-tailwag-api-task` |
| Public API base URL | `https://a9vhnyd929.execute-api.us-east-2.amazonaws.com` |
| API Gateway HTTP API | `a9vhnyd929` |
| API Gateway VPC Link | `dg0r0q` |
| Worker subnets | `subnet-00f10aeac0f8d4ad5,subnet-04c5d8d8ca431dc7f` |
| Worker security group | `sg-0c8c107cc03cec6c4` |

The deploy workflow updates only the core stack and ECS service. The edge stack
is already live and remains a separately managed CloudFormation stack under the
same AWS Application. Normal API and worker deployments must not recreate or
delete it. If the edge API is replaced, update the public base URL in the
GitHub environment and external callers such as Argos.

The AWS account currently has no GitHub Actions OIDC provider and no Tailwag
GitHub deploy role. Create those prerequisites before enabling automatic
deployment. Until then, the CI workflow can validate pull requests, but
`Deploy AWS Dev` cannot assume an AWS role.

## Workflows

[`../.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on pull
requests and pushes to `main`.

It checks:

- Python 3.10 and 3.12 package installs with `.[api,aws]`
- dependency consistency with `pip check`
- the full unittest suite
- local CLI help entry points
- Python package build and `twine check`
- JSON examples and AWS policy/scheduler examples
- deployment shell script syntax
- the core CloudFormation template with `cfn-lint`
- Docker image build without pushing

The CI workflow does not need live Neo4j, OpenAI, Slack, Snowflake, AWS
credentials, or affect model files.

[`../.github/workflows/deploy-aws-dev.yml`](../.github/workflows/deploy-aws-dev.yml)
runs after pushes to `main` and can also be started manually with
`workflow_dispatch`.

The deploy workflow:

1. Assumes a GitHub OIDC AWS role for the `dev` GitHub environment.
2. Confirms the core stack already exists, so ECR remains owned by
   CloudFormation instead of being first created by the image push helper.
3. Runs the unittest suite again against the deployment commit.
4. Validates the CloudFormation template with AWS.
5. Confirms the ECR repository exists before the image push helper runs.
6. Ensures the ECS log group exists.
7. Builds and pushes the API image tagged with the commit SHA.
8. Packages the worker zip and uploads it to
   `s3://$WORKER_CODE_S3_BUCKET/lambda/$GITHUB_SHA/tailwag-memory-worker.zip`.
9. Deploys `aaggarwal1-tailwag-core-dev` with worker Lambdas enabled.
10. Registers a new ECS task definition using the pushed image.
11. Updates `aaggarwal1-tailwag-api-service` and waits for service stability.
12. Runs API smoke checks when `TAILWAG_ALB_BASE_URL` is configured.

## GitHub Configuration

Create a GitHub environment named `dev`.

Required environment variables for the live dev environment:

| Variable | Value |
| --- | --- |
| `AWS_ACCOUNT_ID` | `032318240470` |
| `AWS_ROLE_ARN` | `arn:aws:iam::032318240470:role/aaggarwal1-tailwag-github-actions-deploy` after that role is created |
| `WORKER_CODE_S3_BUCKET` | `aaggarwal1-tailwag-worker-code-032318240470-us-east-2` |
| `REPORTS_BUCKET_NAME` | `aaggarwal1-tailwag-reports-032318240470-us-east-2` |

Optional environment variables with checked-in defaults:

| Variable | Default |
| --- | --- |
| `AWS_REGION` | `us-east-2` |
| `PROJECT_NAME` | `aaggarwal1-tailwag` |
| `ENVIRONMENT_NAME` | `dev` |
| `CORE_STACK_NAME` | `aaggarwal1-tailwag-core-dev` |
| `ECR_REPOSITORY` | `aaggarwal1-tailwag-dev-api` |
| `ECS_CLUSTER` | `aaggarwal1-tailwag-cluster` |
| `ECS_SERVICE` | `aaggarwal1-tailwag-api-service` |
| `ECS_TASK_FAMILY` | `aaggarwal1-tailwag-api-task` |
| `ECS_CONTAINER_NAME` | `tailwag-memory-api` |
| `ECS_EXECUTION_ROLE_NAME` | `aaggarwal1-tailwag-ecs-execution-role` |
| `ECS_TASK_ROLE_NAME` | `aaggarwal1-tailwag-api-task-role` |
| `ECS_LOG_GROUP` | `/ecs/aaggarwal1-tailwag-api` |
| `TAILWAG_ALB_BASE_URL` | unset; set to `https://a9vhnyd929.execute-api.us-east-2.amazonaws.com` for deployed API smoke checks; the variable name is retained for workflow compatibility |
| `RUN_API_WRITE_SMOKE` | `false`; set to `true` to write and read a CI smoke episode |
| `RUN_WORKER_SMOKE` | `false`; set to `true` to enqueue memory and report smoke jobs |
| `WORKER_SUBNET_IDS` | unset; live dev value is `subnet-00f10aeac0f8d4ad5,subnet-04c5d8d8ca431dc7f` |
| `WORKER_SECURITY_GROUP_IDS` | unset; live dev value is `sg-0c8c107cc03cec6c4` |
| `NEO4J_URI_SECRET_ID` | `aaggarwal1-tailwag/neo4j-uri` |
| `NEO4J_USER_SECRET_ID` | `aaggarwal1-tailwag/neo4j-user` |
| `NEO4J_PASSWORD_SECRET_ID` | `aaggarwal1-tailwag/neo4j-password` |
| `OPENAI_API_KEY_SECRET_ID` | `aaggarwal1-tailwag/openai-api-key` |
| `SLACK_BOT_TOKEN_SECRET_ID` | `aaggarwal1-tailwag/slack-bot-token` |
| `TAILWAG_API_BEARER_TOKEN_SECRET_ID` | `aaggarwal1-tailwag/api-bearer-token` |

Optional environment secret:

| Secret | Use |
| --- | --- |
| `TAILWAG_API_BEARER_TOKEN` | Enables authenticated provider health smoke check after ECS stabilizes |

Configure `WORKER_SUBNET_IDS` and `WORKER_SECURITY_GROUP_IDS` with the live
values above. Omitting them would move updated workers out of the VPC and break
their private Neo4j connection. Configure `TAILWAG_ALB_BASE_URL` with the
public API Gateway URL despite the legacy variable name; GitHub-hosted runners
cannot reach the internal ALB.

The `TAILWAG_API_BEARER_TOKEN` GitHub secret must contain the current value of
Secrets Manager secret `aaggarwal1-tailwag/api-bearer-token`. Never put the
token in a GitHub variable, workflow file, command argument, or repository.

Restrict the `dev` GitHub environment to the `main` branch before allowing the
OIDC role to trust `repo:aaggarwal1-chwy/tailwag-memory:environment:dev`.

## AWS OIDC Role

Create a GitHub Actions OIDC provider for `token.actions.githubusercontent.com`.
The provider does not currently exist in account `032318240470`. Its intended
ARN is:

```text
arn:aws:iam::032318240470:oidc-provider/token.actions.githubusercontent.com
```

Create the dev deploy role as
`aaggarwal1-tailwag-github-actions-deploy`, attach the dev deployment policy,
and use this role ARN for `AWS_ROLE_ARN`:

```text
arn:aws:iam::032318240470:role/aaggarwal1-tailwag-github-actions-deploy
```

Use these example IAM documents, replacing `<account-id>`:

- [`../deploy/aws/iam/tailwag-github-actions-deploy-trust.example.json`](../deploy/aws/iam/tailwag-github-actions-deploy-trust.example.json)
- [`../deploy/aws/iam/tailwag-github-actions-deploy-policy.example.json`](../deploy/aws/iam/tailwag-github-actions-deploy-policy.example.json)

The trust policy is scoped to the `dev` GitHub environment. The permissions
policy is intentionally dev-specific and should not be reused for production
without separate resource names and a separate GitHub environment.

## First Deployment

Before the first workflow deploy:

1. Complete the one-time AWS setup described in
   [AWS Deployment And Operations](aws-deployment.md) through ECS service
   creation.
2. Confirm the core CloudFormation stack already exists. The workflow refuses to
   push an image before the stack exists so the ECR repository stays stack-owned.
3. Confirm the stack-created ECR repository exists.
4. Create the worker code bucket.
5. Configure the GitHub `dev` environment variables.
6. Create the GitHub OIDC provider and AWS deploy role described above, then
   set `AWS_ROLE_ARN`.
7. Set `WORKER_SUBNET_IDS` and `WORKER_SECURITY_GROUP_IDS` when Neo4j is private
   in the VPC.
8. Set `TAILWAG_ALB_BASE_URL` to the public API Gateway URL and add the
   `TAILWAG_API_BEARER_TOKEN` environment secret.
9. Confirm the core stack remains associated with
   `aaggarwal1-tailwag-dev` through `APPLY_APPLICATION_TAG`.
10. Start `Deploy AWS Dev` manually from GitHub Actions.

If the workflow succeeds, future merges to `main` deploy automatically.

## Testing

For a PR, the test is the `CI` workflow. It should pass before merge.

For a deploy, the test is the `Deploy AWS Dev` workflow plus these AWS-side
checks:

```bash
export TAILWAG_BASE_URL=https://a9vhnyd929.execute-api.us-east-2.amazonaws.com

curl "$TAILWAG_BASE_URL/health"
curl -H "Authorization: Bearer $TAILWAG_API_BEARER_TOKEN" \
  "$TAILWAG_BASE_URL/argos/providers/memory/resources/memory/health"
```

For worker validation, use the manual SQS smoke tests in
[AWS Deployment And Operations](aws-deployment.md) after a deploy, or set
`RUN_API_WRITE_SMOKE=true` and `RUN_WORKER_SMOKE=true` for the GitHub `dev`
environment once the smoke writes are acceptable in dev. Confirm:

- Lambda logs have no handler startup errors
- SQS DLQs remain empty
- report jobs write expected files to the reports bucket

## Rollback

API rollback:

1. Find the prior ECS task definition revision for
   `aaggarwal1-tailwag-api-task`.
2. Update `aaggarwal1-tailwag-api-service` back to that revision.
3. Wait for ECS service stability and rerun health checks.

Worker rollback:

1. Find the previous worker artifact key under
   `s3://$WORKER_CODE_S3_BUCKET/lambda/<commit-sha>/tailwag-memory-worker.zip`.
2. Rerun the core CloudFormation deploy with that `WorkerCodeS3Key`.
3. Confirm Lambda versions load and worker DLQs stay empty.

Schema initialization remains manual until Tailwag has explicit versioned
migrations.
