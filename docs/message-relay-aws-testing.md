# Message Relay On AWS

This guide owns relay-specific rollout gates and smoke tests. Use
[AWS Deployment And Operations](aws-deployment.md) for topology and
[AWS Manual Updates](aws-manual-updates.md) for command-by-command deployment,
schema, verification, and rollback procedures.

## Deployment Shape

Relay reuses the existing Tailwag resources:

- ECS API and API Gateway for robot-authenticated relay routes
- Neo4j for `RelayMessage` state
- memory SQS queue and Lambda for `relay_maintenance`
- DynamoDB job-idempotency table
- EventBridge Scheduler and the memory-jobs DLQ

Maintenance expires eligible messages, releases abandoned pre-playback claims,
and marks stale in-progress playback `delivery_uncertain`. It never deletes
message bodies or automatically replays uncertain delivery.

## Credentials And Schedule

Store one JSON object in Secrets Manager, with one unique token per stable robot
ID:

```json
{
  "robot-bos3-01": "<opaque-token-for-bos3-01>",
  "robot-bos3-02": "<different-token-for-bos3-02>"
}
```

Inject its complete ARN into the ECS container as
`TAILWAG_ROBOT_API_TOKENS_JSON`. The ECS execution role needs
`secretsmanager:GetSecretValue` for that exact ARN. Do not store tokens in
environment-value JSON, scheduler payloads, logs, fixtures, shell history, or
source control. Duplicate token values make relay authentication fail closed.

Use
[`deploy/aws/scheduler/relay-maintenance-schedule.example.json`](../deploy/aws/scheduler/relay-maintenance-schedule.example.json)
to target the existing memory queue:

```json
{
  "job_type": "relay_maintenance",
  "job_id": "relay-maintenance-<aws.scheduler.execution-id>",
  "claim_timeout_seconds": 120
}
```

Omit `now` in deployed jobs. It exists only for deterministic tests. Keep
`claim_timeout_seconds` above measured claim-to-playback-start latency plus an
operating margin; it is not a Lambda timeout, schedule interval, or playback
deadline.

Create or update the schedule in `DISABLED` state. Its role needs
`sqs:SendMessage` for both the memory queue and memory-jobs DLQ.
Use the canonical
[relay schedule procedure](aws-manual-updates.md#manage-the-relay-maintenance-schedule)
for disabled-first create/update, enable, and rollback.

## Local Gates

Run the focused worker tests:

```bash
PYTHONPATH=src python3 -m unittest tests.test_aws_jobs tests.test_aws_workers
```

With a local Neo4j test database, seed:

1. an expired undelivered message
2. an abandoned `claimed` or `permission_granted` message
3. a stale `delivering` message
4. eligible and recently claimed controls that must not change

Call `RelayMessageService.run_maintenance` with fixed `now` and verify
`expired_count`, `claims_released_count`, and `uncertain_count`. Run it again
with the same time to verify idempotent state.

Also run the full relay and HTTP contract suite from
[Robot Message Relay](message-relay.md#verification). Local tests do not prove
ECS secret injection, deployed readiness, network access, SQS/Lambda handling,
or alarms.

## Deployment Gates

Confirm the active account, role, region, and resource prefix before any
mutation:

```bash
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
aws configure get region
```

Follow [AWS Manual Updates](aws-manual-updates.md) to deploy immutable API and
worker artifacts. Do not enable the schedule until all gates pass:

- `relay_message_id` exists
- `relay_message_status`, `relay_message_delivery`, and
  `relay_message_expires_at` are `ONLINE`
- deployed Neo4j `EXPLAIN`/`PROFILE` uses `relay_message_delivery` for claim and
  `relay_message_status` for maintenance at representative retained volume
- ECS is stable on the intended task revision
- the task definition contains one robot-token secret entry using the complete
  secret ARN
- ECS tasks were restarted after any robot-token, Neo4j, or OpenAI secret change
- `/health` passes for liveness and `/ready` passes dependency preflight
- a robot-token `sender_statuses` request succeeds and returns no `body`
- the memory Lambda uses the intended artifact and its SQS event source mapping
  is enabled
- memory queue and DLQ are empty before the smoke job
- relevant worker, queue-age, and DLQ alarms exist, have actions enabled, and
  are not in `ALARM`

The administrative bearer token is valid for memory APIs, not relay routes.

## Deployed Smoke Test

Use synthetic people and a non-sensitive message. Exercise the sender and
recipient lifecycle from [Robot Message Relay](message-relay.md):

- policy check, explicit sender confirmation, and create
- body-free claim and recipient permission
- begin, exact playback, and completion
- decline without receipt acknowledgement
- pre-audio failure returning to pending with sender-visible failure details
- post-audio failure becoming terminal `delivery_uncertain`
- sender-specified expiry and default expiry
- status requests remaining body-free

Send one uniquely identified maintenance job to the existing memory queue:

```bash
aws sqs send-message \
  --region "$AWS_REGION" \
  --queue-url "$TAILWAG_MEMORY_JOBS_QUEUE_URL" \
  --message-body '{"job_type":"relay_maintenance","job_id":"relay-maintenance-smoke-<unique-id>","claim_timeout_seconds":120}'
```

Verify:

- the queue drains and the DLQ remains empty
- the memory Lambda has no new errors or throttles
- the idempotency row reaches `succeeded`
- the result reports all three maintenance counts
- seeded expired, abandoned, stale-delivering, and control records transition
  as expected
- no relay body is logged, returned before permission, changed, or deleted

Use a new job ID for each intentional rerun. A reused ID tests idempotency; it
does not rerun the job.

Enable the schedule only after the manual job and alarm gates pass. Round-trip
the complete deployed schedule, remove read-only response fields, change only
`State` to `ENABLED`, update it, and verify the first scheduled execution
creates a distinct successful idempotency row. The exact update commands are in
[AWS Manual Updates](aws-manual-updates.md#manage-the-relay-maintenance-schedule).

## Rollback

If maintenance is wrong:

1. disable only the relay-maintenance schedule
2. leave the shared memory queue and other schedules running
3. deploy the previous immutable worker artifact
4. verify the Lambda version and event source mapping
5. inspect affected relay state before repair

Do not purge the shared queue or delete relay records. Restore a prior
Secrets Manager version and force a new ECS deployment to roll back a token
mapping. Secret deletion, IAM expansion, public exposure, destructive repair,
and material cost increases require separate approval.
