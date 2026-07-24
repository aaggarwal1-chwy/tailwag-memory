# Message Relay On AWS

## Deployment Shape

The message relay uses the existing Tailwag deployment instead of adding a
second API or worker fleet:

- the existing API Gateway, internal load balancer, and ECS API serve the
  authenticated relay endpoints
- the existing Neo4j database stores relay messages and their lifecycle state
- the existing memory SQS queue and memory Lambda run `relay_maintenance`
- the existing DynamoDB job-idempotency table makes each scheduled cleanup job
  retry-safe
- EventBridge Scheduler sends cleanup jobs to the existing memory queue

Relay maintenance expires messages whose delivery window has ended and releases
claims that were abandoned before playback. Claims with uncertain playback
state remain unavailable for automatic replay and are counted separately.

## Robot Credentials

Every robot must use its own opaque bearer token. Store the mapping as one
Secrets Manager `SecretString` containing a JSON object whose keys are stable
robot IDs and whose values are independently generated tokens:

```json
{
  "robot-bos3-01": "<opaque-token-for-bos3-01>",
  "robot-bos3-02": "<different-opaque-token-for-bos3-02>"
}
```

Use a secret name within the confirmed Tailwag resource prefix, for example
`<resource-prefix>/robot-api-tokens-json`. Resolve its complete ARN with
`aws secretsmanager describe-secret --query ARN --output text`; do not assemble
an ARN from the secret name because the generated suffix is part of the
complete ARN. Inject the `SecretString` into the existing ECS API container as
`TAILWAG_ROBOT_API_TOKENS_JSON` by setting the task-definition secret's
`valueFrom` to that complete ARN. Do not put tokens in a task-definition
environment value, scheduler payload, command argument, test fixture, log, or
source-controlled file.

The ECS task execution role must be allowed to call
`secretsmanager:GetSecretValue` for the exact robot-token secret ARN, in
addition to any other runtime secrets it already injects. Verify the decision
for the deployed `executionRoleArn` with
`aws iam simulate-principal-policy`; the application task role does not need
that permission when ECS injects the secret during task startup. Follow the
upserting `jq` procedure in
[AWS Manual Updates](aws-manual-updates.md#deploy-api-changes) so an existing
entry is replaced and a missing entry is added without duplicating the name.
After changing the mapping, register a new task-definition revision and let the
existing ECS service replace its tasks. A token identifies exactly one robot;
duplicate token values make relay authentication fail closed.

Keep the existing administrative `TAILWAG_API_BEARER_TOKEN` for non-robot API
operations. Relay routes require a robot-bound token, so the administrative
token cannot be used as a robot identity.

## Scheduled Maintenance

Create an EventBridge Scheduler schedule in the existing Tailwag schedule group.
Target the existing memory SQS queue with the existing scheduler role. Use a
unique Scheduler execution ID in every job ID:

```json
{
  "job_type": "relay_maintenance",
  "job_id": "relay-maintenance-<aws.scheduler.execution-id>",
  "claim_timeout_seconds": 120
}
```

Omit `now` in deployed jobs so the service uses its current UTC time. An
explicit ISO-8601 `now` is available for deterministic local tests only.
`claim_timeout_seconds` must be positive and should be comfortably longer than
the robot's normal envelope-to-playback interval. Reducing it can cause an
active claim to look abandoned. A five-minute schedule is a reasonable
development starting point; choose the production cadence only after observing
real playback latency and queue age.

Render
[`deploy/aws/scheduler/relay-maintenance-schedule.example.json`](../deploy/aws/scheduler/relay-maintenance-schedule.example.json)
with the confirmed group, queue, DLQ, scheduler-role, account, and region
values. The example is intentionally `DISABLED`, retries a failed target
invocation at most twice while it is no more than 15 minutes old, and sends
exhausted invocations to the existing memory-jobs DLQ. The scheduler execution
role therefore needs `sqs:SendMessage` on both the memory queue and its DLQ;
keep
[`deploy/aws/iam/tailwag-scheduler-policy.example.json`](../deploy/aws/iam/tailwag-scheduler-policy.example.json)
aligned with both ARNs.

Create the schedule in its disabled state:

```bash
aws scheduler create-schedule \
  --region "$AWS_REGION" \
  --cli-input-json file:///tmp/relay-maintenance-schedule.json
```

If the schedule already exists, render the same complete input and use
`aws scheduler update-schedule` instead. Never omit required update fields or
enable the schedule as part of its first deployment.

No new Lambda, queue, DLQ, idempotency table, VPC access, or Neo4j credential is
required. Package the changed Tailwag code in the same immutable worker ZIP,
upload it to the existing worker-code bucket, update the core stack's
`WorkerCodeS3Bucket` and `WorkerCodeS3Key`, and verify the memory Lambda event
source mapping remains enabled.

## Schema Gate

Before replacing the API tasks or creating the disabled schedule, run the
idempotent schema initializer from a network path that can reach Neo4j:

```bash
tailwag schema init
```

Then run `SHOW CONSTRAINTS` and `SHOW INDEXES` as described in
[AWS Manual Updates](aws-manual-updates.md#initialize-and-verify-the-graph-schema).
Do not continue until `relay_message_id` exists and
`relay_message_status`, `relay_message_delivery`, and
`relay_message_expires_at` are all `ONLINE`.

## Readiness And The 120-Second Claim Window

The open `/health` endpoint is a liveness check, not full relay readiness.
Before enabling recurring maintenance, require all of the following:

- the relay constraint and three indexes passed the schema gate
- ECS is stable on the intended task revision and the selected container has
  one `TAILWAG_ROBOT_API_TOKENS_JSON` entry referencing the complete ARN
- the ALB target is healthy and both open and administrative health checks pass
- a read-only `sender_statuses` request using a robot-scoped token and a known
  fixture identity authenticates successfully without returning message bodies
- the memory Lambda is on the intended immutable artifact, its SQS event source
  mapping is enabled, and the memory queue and DLQ are empty before the smoke
  job
- one manual relay-maintenance job succeeds and its idempotency record reaches
  `succeeded`

The default `claim_timeout_seconds: 120` is a stale-claim recovery threshold,
not a Lambda timeout, schedule interval, HTTP timeout, or playback deadline.
Measure the time from successful envelope claim through playback start,
including recognition, permission dialogue, speech preparation, network
retries, and normal robot scheduling delay. Keep the threshold above the
observed high percentile plus an operating margin. Raise it before rollout if
legitimate claims can remain pre-playback for 120 seconds; lower it only after
evidence shows active claims cannot be released. Re-test abandoned-claim
recovery whenever this value changes.

## Local Verification

Run the focused parsing, serialization, and worker tests:

```bash
python -m unittest tests.test_aws_jobs tests.test_aws_workers
```

With a local Neo4j test database configured, create fixtures covering:

1. an undelivered message whose `expires_at` is before `now`
2. a claimed message whose claim age exceeds `claim_timeout_seconds` and whose
   playback has not started
3. an in-progress or failed-after-audio-start message whose playback outcome is
   uncertain
4. a currently eligible message and a recently claimed message that must not
   change

Invoke `RelayMessageService.run_maintenance` with a fixed `now`, then verify the
expired count, released-claim count, and uncertain count. Run it again with the
same `now` and confirm that counts and stored state demonstrate idempotent
maintenance.

## Deployed Smoke Test

Before any account mutation, verify the active identity and region, then compare
the account, region, and resource prefix with the intended environment:

```bash
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
aws configure get region
```

Send one manually identified job to the existing memory queue. Use a new job ID
for each intentional rerun:

```bash
aws sqs send-message \
  --region <region> \
  --queue-url <memory-queue-url> \
  --message-body '{"job_type":"relay_maintenance","job_id":"relay-maintenance-smoke-<unique-id>","claim_timeout_seconds":120}'
```

Verify all of the following without printing message bodies or credentials:

- the memory queue drains and its DLQ remains empty
- the memory Lambda has no new errors or throttles
- the DynamoDB idempotency row reaches `succeeded`
- the result contains `expired_count`, `claims_released_count`, and
  `uncertain_count`
- seeded expired and abandoned-claim records transition as expected
- eligible, recent-claim, delivered, declined, and uncertain records do not
  become deliverable incorrectly
- an authenticated robot can claim an envelope only with its own configured
  token and assigned robot identity

Before enabling the schedule, confirm that the existing alarm actions are
enabled and that these alarms are not in `ALARM` state:

```bash
aws cloudwatch describe-alarms \
  --region "$AWS_REGION" \
  --alarm-names \
    "${PROJECT_NAME}-${ENVIRONMENT_NAME}-memory-worker-errors" \
    "${PROJECT_NAME}-${ENVIRONMENT_NAME}-memory-worker-throttles" \
    "${PROJECT_NAME}-${ENVIRONMENT_NAME}-memory-jobs-oldest-message" \
    "${PROJECT_NAME}-${ENVIRONMENT_NAME}-memory-jobs-dlq-visible" \
  --query MetricAlarms \
  --output json \
| jq -e '
    length == 4
    and all(.[];
      .ActionsEnabled == true
      and .StateValue != "ALARM"
    )
  ' >/dev/null
```

Enable the recurring schedule only after the manual job and alarm gate succeed.
Verify the first scheduled execution creates a distinct idempotency row and
completes.

Enable it by round-tripping the complete deployed schedule, removing read-only
response fields, and changing only `State`:

```bash
aws scheduler get-schedule \
  --region "$AWS_REGION" \
  --group-name "$SCHEDULER_GROUP" \
  --name "$RELAY_MAINTENANCE_SCHEDULE" \
  --output json \
| jq '
    del(.Arn, .CreationDate, .LastModificationDate)
    | .State = "ENABLED"
  ' \
> /tmp/relay-maintenance-schedule-enable.json

aws scheduler update-schedule \
  --region "$AWS_REGION" \
  --cli-input-json file:///tmp/relay-maintenance-schedule-enable.json

aws scheduler get-schedule \
  --region "$AWS_REGION" \
  --group-name "$SCHEDULER_GROUP" \
  --name "$RELAY_MAINTENANCE_SCHEDULE" \
  --query '{
    state:State,
    group:GroupName,
    retry:Target.RetryPolicy,
    dlq:Target.DeadLetterConfig.Arn
  }'
```

Remove the temporary rendered schedule files after verification.

## Alarms And Rollback

Reuse the existing memory Lambda error/throttle alarms, memory queue
oldest-message alarm, and memory DLQ alarm. Add an application metric or
structured-log alarm for a sustained nonzero `uncertain_count` if that condition
requires operator review. Never log relay bodies, claim tokens, or bearer
tokens.

The Scheduler `DeadLetterConfig` points at that alarmed memory-jobs DLQ, so a
target invocation that exhausts the configured retry policy becomes visible to
operators. Treat a missing alarm, disabled action, or visible DLQ message as a
rollout blocker.

If maintenance behaves incorrectly:

1. disable only the relay-maintenance schedule
2. leave the memory queue and other schedules running
3. deploy the previous immutable worker artifact through the core stack
4. verify the memory Lambda version and event source mapping
5. inspect affected relay state before attempting any repair

Do not purge the shared memory queue or delete relay records as rollback steps.
Token rollback means restoring the prior Secrets Manager version and forcing a
new ECS deployment; credential rotation and secret deletion require explicit
approval. Treat any change that broadens IAM access, exposes the API publicly,
replaces data resources, or materially increases cost as a separate sensitive
operation.
