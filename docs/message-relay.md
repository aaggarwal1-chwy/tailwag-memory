# Robot Message Relay

## Purpose

Message relay lets a recognized employee ask one physical robot to speak an
exact, short message to another recognized employee later. Tailwag owns durable
state and lifecycle enforcement. Argos owns conversation flow, recognition,
sender confirmation, permission prompting, and controlled audio playback.

This is deliberately not email, chat, a general notification service, or a
durable-memory feature. A `RelayMessage` is a first-class operational record,
not a `MemoryItem`.

## Identity And Authentication

Every sender and recipient is resolved to exactly one `Person` by
`lower(trim(Person.email))`. Email is the canonical unique lookup key; display
names are snapshots used only to make prompts sound natural. A missing,
duplicate, archived, or self-matching identity is rejected.

Every relay API call requires a robot-bound bearer token. Tailwag derives the
stable `Robot.id` from `TAILWAG_ROBOT_API_TOKENS_JSON`; callers cannot choose a
robot ID in a request body. The existing administrative bearer token remains
valid for memory APIs but receives `403` from relay routes.

The robot credential is the server trust boundary for local recognition,
sender confirmation, and recipient permission. Tailwag verifies canonical
email, assigned robot, opaque claim token, and prior state, but it cannot
independently observe the room. A compromised robot token can assert actions
for people assigned to that robot, so each token must be unique, narrowly
distributed, monitored, and rotated if exposure is suspected.

Example local configuration:

```dotenv
TAILWAG_ROBOT_API_TOKENS_JSON={"robot-bos3-01":"replace-with-an-opaque-secret"}
```

Do not log, commit, or put real tokens in command history.

## Sender Flow

1. Argos recognizes the current turn owner and obtains their canonical email.
2. `message.relay_prepare` resolves both people, validates dates and limits,
   and runs the workplace-safety screen without creating a durable message.
3. Argos reads back the exact recipient and exact message text.
4. The same recognized sender must explicitly confirm that prepared draft.
5. `message.relay_confirm_send` consumes the short-lived, single-use local
   confirmation token and calls Tailwag `create`.

Separating prepare from confirm prevents the language model from turning one
ambiguous request into an immediate durable send. The confirmation token is
bound to the owner, recipient, exact body, timing, and robot. It is not a relay
claim token and is never accepted by recipient endpoints.

Workplace-safety screening sends the exact proposed body to the configured
OpenAI Responses API during prepare and repeats the screen immediately before
durable create to prevent a stale or tampered decision. Deployment approval
must cover that external processing boundary and the message data
classification. If screening is unavailable or malformed, creation fails
closed.

The body is limited to 500 characters. The default and maximum expiry are 30
days; a sender may explicitly choose a shorter expiry. A phrase such as
“tomorrow” sets `deliver_after`, not expiry, unless the sender explicitly says
the message expires then. Each sender is limited to five creates per UTC day,
and each sender-recipient pair may have at most three active messages.

## Recipient Flow

1. Stable face/owner recognition supplies the intended recipient's canonical
   email.
2. Argos claims one due envelope. The envelope contains identity and timing
   metadata plus an opaque claim token, never the body.
3. Argos asks that person for permission to hear a message from the named
   sender. The response must still belong to the same recognized person.
4. A decline is terminal. A deferral returns the message to pending.
5. Only `permission` can release the body, and only when robot, claim token,
   state, and canonical recipient email all match.
6. Argos calls `begin_delivery` immediately before controlled TTS, submits the
   returned body unchanged as TTS input, and calls `complete` only after natural
   playback completion.

There is no acknowledgement-of-receipt step. Existing permission-to-speak
behavior applies even when bystanders are present.

Tailwag transitions use the authenticated robot, opaque claim token, and
expected prior state as compare-and-set guards. Each mutating Cypher query
first acquires an explicit Neo4j write lock by setting a temporary internal
property, then rechecks the expected state or applicable rate limit while that
lock is held before applying the change. The temporary property is removed in
the same transaction. Create serializes on the sender, claim serializes on the
assigned robot and candidate messages, and later transitions serialize on the
message.

These lock properties are transaction-scoped implementation details, not graph
state. Tailwag does not persist relay send counters on `Person`, claim counters
on `Robot`, or any other lock-counter model. Rate limits are computed from
`RelayMessage` records after the sender lock is acquired.

```text
pending -> claimed -> permission_granted -> delivering -> delivered
                  \-> declined
claimed -> pending                         (snooze or abandoned claim)
delivering -> pending                      (failure before audio starts)
delivering -> delivery_uncertain           (audio started or may have started)
pending/claimed/permission_granted -> expired
```

`delivery_uncertain` is terminal and is never automatically replayed. This
trades possible non-delivery for protection against speaking the same private
message twice. Sender status requests include `declined`,
`delivery_uncertain`, and `expired`; a pre-audio failure remains pending but
includes its last failure time and reason. Status responses never return the
body and are reported only when the sender asks.

## Graph Model

```cypher
(sender:Person)-[:SENT_RELAY]->(message:RelayMessage)
(message)-[:FOR_RECIPIENT]->(recipient:Person)
(message)-[:ASSIGNED_TO]->(robot:Robot)
```

`RelayMessage` stores:

- `id`, exact `body`, and JSON metadata
- canonical email and display-name snapshots
- authenticated `assigned_robot_id`
- `status`, `created_at`, `updated_at`, `deliver_after`, and `expires_at`
- claim, permission, playback, delivery, decline, and failure timestamps
- opaque `claim_token`, bounded failure reason, audio-start evidence, and
  attempt count

Schema initialization creates a unique `RelayMessage.id` constraint and indexes
for status, assigned-robot delivery ordering, and expiry.

Temporary `_relay_*_lock` and create-token properties may exist only while a
write transaction is executing. Successful transactions remove them; they are
not part of the durable graph contract.

The public package adds:

- `RelayMessageInput`
- `RelayPolicyResult`
- `RelayMessageEnvelope`
- `RelayDeliveryAttempt`
- `RelayMessageStatus`
- `RelayTransitionResult`
- `RelayMaintenanceResult`
- `RelayMessageService`

## HTTP Contract

All routes are below:

```text
/argos/providers/message-relay/resources/messages/request
```

Operations are `policy_check`, `create`, `claim`, `permission`, `decline`,
`snooze`, `begin_delivery`, `complete`, `playback_failure`, and
`sender_statuses`. Relay responses intended before permission and sender-status
responses have no `body` field. `permission` is the only successful response
that includes body text.

`GET /health` is an unauthenticated liveness check and deliberately does not
open Neo4j or validate relay dependencies. `GET /ready` is the deployment
readiness check: it validates robot-token authentication configuration, OpenAI
safety-policy configuration including bounded timeout/retry settings, Neo4j
connectivity, and the required online relay constraint and indexes. Readiness
returns `503` when any preflight check fails.

Safety screening defaults to an 8-second timeout, permits a configured timeout
from 1 through 10 seconds, and allows at most one retry.
Relay HTTP errors distinguish upstream failures:

- `503` when safety screening times out, the provider is unavailable, or its
  configuration is invalid
- `502` when the provider returns a malformed decision

Caller validation remains `422`; policy rejection is `403`; rate limiting is
`429`; duplicate IDs and compare-and-set conflicts are `409`.

## Retention And Deletion

Relay expiry controls delivery eligibility only. It never deletes, redacts, or
overwrites `RelayMessage.body`; the exact body remains in Neo4j after delivery,
decline, failure, or expiry. Under the selected standard-retention policy, the
sender's original conversation may also exist in episode transcripts, derived
embeddings, logs, and backups according to their independent retention rules.
Operators must not describe expiry as erasure.

There is no relay-message deletion or body-redaction operation. Targeted CLI
deletion does not accept `RelayMessage`, and deleting a `Person` does not delete
relay nodes or their bodies. Removing a sender relationship makes that relay
ineligible for delivery, but preserves its exact body in Neo4j. Backups retain
historical copies under their normal retention rules.

## Verification Gates

The unit and HTTP contract suite is the first gate and does not require a live
Neo4j instance:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Real Neo4j is a separate required gate for transaction behavior:

```bash
docker compose up -d neo4j
docker compose --profile api up --build api
```

Initialize schema and seed two `Person` nodes with unique emails plus the
configured `Robot`. Confirm `/health` stays lightweight and `/ready` succeeds
only after auth, OpenAI, Neo4j, and relay schema configuration are valid. Use a
local robot token to exercise the HTTP sequence, including concurrent create,
claim, and transition requests against Neo4j. Verify specifically that:

- policy check does not create a node
- create rejects a message without unique sender/recipient identities
- claim and sender-status JSON do not contain `body`
- a wrong recipient email, robot token, claim token, or prior state cannot
  release content
- completion before permission/begin fails
- exact whitespace and punctuation reach controlled TTS unchanged
- failure before audio starts returns to pending
- failure after audio starts becomes `delivery_uncertain` and cannot be claimed
- decline and expiry are visible to the sender when requested

Passing mocks or query-shape tests does not close the real-Neo4j concurrency
gate. Record the database version and results of contention tests.

Argos fake-provider/coordinator tests can run on macOS, but controlled TTS and
the camera, microphone, face/voice ownership, and Linux audio path require a
real Ubuntu robot. That hardware run is a distinct gate; see the Argos relay
documentation.

## AWS Deployment Test

AWS resources and smoke-test commands are in
[Message Relay AWS Testing](message-relay-aws-testing.md). The feature reuses
the existing API, Neo4j database, memory SQS queue/DLQ, memory Lambda,
idempotency table, scheduler role, and alarms. New setup is limited to:

- a Secrets Manager value containing the robot-ID-to-token JSON mapping
- the corresponding ECS task-definition secret injection
- a relay maintenance schedule targeting the existing memory queue
- the updated API image and worker artifact

Deploy to a development environment first. Seed synthetic people and a
non-sensitive message, run the full state sequence, inject pre-audio and
post-audio failures, inspect graph state without printing bodies, then verify
queue, Lambda, API, DLQ, and alarm behavior before enabling the schedule.

The AWS development-environment smoke test is also a distinct gate. Local and
mocked tests do not establish ECS readiness behavior, Secrets Manager
injection, queue/Lambda maintenance, alarms, or deployed network access.

## Operational Boundaries

- Recognition quality is a safety boundary. Argos must require stable ownership
  for both confirmation and recipient permission, and must abort on owner
  change.
- A compromised robot credential can act as that robot. Use a distinct random
  token per robot, narrow secret distribution, rotation, and access monitoring.
- Model-based safety screening can be unavailable or imperfect. Invalid or
  unavailable decisions fail closed; production rollout should monitor reject
  rates without logging message bodies.
- `delivery_uncertain` needs an operator/support policy because automatic replay
  is intentionally prohibited and cancellation/editing are not implemented.
- The explicitly selected permanent-body rule means sensitive text outlives
  relay expiry in the relay node and may also persist in transcripts and
  backups. Any future deletion or strict-erasure product would require a
  separate, explicitly approved design change.
- Rate limits serialize creates on the canonical sender node. Load-test contention
  before materially raising send volume or adding a fleet-wide deployment.
