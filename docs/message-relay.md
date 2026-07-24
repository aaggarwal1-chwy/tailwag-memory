# Robot Message Relay

Message relay lets a recognized employee ask a physical robot to deliver an
exact, short message to another recognized employee. Tailwag stores the message
and enforces its lifecycle. Argos owns recognition, explicit sender
confirmation, recipient permission, and controlled text-to-speech (TTS).

A `RelayMessage` is an operational delivery record, not a `MemoryItem`, email,
or chat message.

## Safety Contract

- Resolve sender and recipient to exactly one active `Person` by
  `lower(trim(email))`. Reject missing, duplicate, archived, or self-matching
  identities.
- Authenticate every request with a unique robot bearer token configured in
  `TAILWAG_ROBOT_API_TOKENS_JSON`. The token selects the robot; request bodies
  cannot.
- Run `policy_check`, read back the exact recipient and body, and obtain
  explicit confirmation from the same recognized sender before calling
  `create`.
- Claim a body-free envelope and obtain permission from the same recognized
  recipient before calling `permission`. Only `permission` returns the body.
- Send the returned body to controlled TTS unchanged. Call `begin_delivery`
  immediately before playback and `complete` only after natural completion.
- Do not ask for or record a receipt acknowledgement. Sender statuses are
  returned only when the sender asks and never include the body.

The robot credential is the trust boundary for local recognition, confirmation,
and permission. A compromised credential can act as its assigned robot, so use
one random token per robot, distribute it narrowly, and rotate it after suspected
exposure.

## Sender Flow

1. Recognize the sender and collect the exact recipient, body, delivery time,
   and optional expiry.
2. Call `policy_check`. It resolves both people and screens the exact body
   without creating a message.
3. Read back the exact recipient and body.
4. Require explicit confirmation from the same recognized sender.
5. Call `create` with the unchanged payload.

Tailwag repeats identity, validation, and policy checks during `create`. Safety
screening uses the configured OpenAI Responses API and fails closed if the
provider is unavailable or returns an invalid decision. Deployment approval
must cover this external processing boundary.

By default, a message is deliverable immediately and expires after
`TAILWAG_RELAY_DEFAULT_EXPIRY_DAYS` (30 by default). A sender can specify an
earlier `deliver_after` and an explicit future `expires_at`, but expiry cannot
exceed that configured window. “Deliver tomorrow” changes `deliver_after`; it
does not shorten expiry unless the sender says so.

Default limits are 500 body characters, five creates per sender per UTC day,
and three active messages per sender-recipient pair.

## Recipient Flow

1. Recognize the recipient and call `claim` with their canonical email.
2. Use the body-free envelope to ask permission to hear a message from its
   named sender.
3. Confirm the responder is still the same recognized recipient.
4. Call `permission`, `decline`, or `snooze`.
5. After permission, call `begin_delivery`, speak the returned body unchanged,
   then call `complete`.
6. If playback fails, call `playback_failure` with accurate `audio_started`
   evidence.

A failure before audio starts returns the message to `pending` and is visible
to the sender through `last_failure_reason` and `last_failure_at`. A failure
after audio starts becomes terminal `delivery_uncertain`; Tailwag will not
replay it automatically.

```text
pending -> claimed -> permission_granted -> delivering -> delivered
                  \-> declined
claimed/permission_granted -> pending      (snooze or abandoned claim)
delivering -> pending                      (failure before audio starts)
delivering -> delivery_uncertain           (audio started or may have started)
pending/claimed/permission_granted -> expired
```

Transitions compare the authenticated robot, claim token, canonical recipient
where applicable, and expected prior state. Neo4j writes use temporary lock
properties that are removed in the same transaction; counters and locks are not
durable `Person` or `Robot` state.

## HTTP Example

All endpoints are under:

```text
/argos/providers/message-relay/resources/messages/request
```

Use a robot-scoped token:

```bash
export TAILWAG_URL=http://localhost:8000
export ROBOT_TOKEN=<robot-scoped-token>
export RELAY_API="$TAILWAG_URL/argos/providers/message-relay/resources/messages/request"
```

Check policy before sender confirmation:

```bash
curl -fsS "$RELAY_API/policy_check" \
  -H "Authorization: Bearer $ROBOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "id": "relay-20260724-001",
      "sender_email": "alice@example.com",
      "recipient_email": "bob@example.com",
      "body": "Please meet me by the reception desk at 3 PM.",
      "metadata": {"source": "argos"}
    }
  }'
```

Omitting `deliver_after` makes the message immediately eligible; omitting
`expires_at` uses the configured default. To honor a sender-specified window,
include timezone-aware ISO-8601 values where `deliver_after < expires_at` and
`expires_at` is within the configured maximum.

After the same sender explicitly confirms the exact read-back, send the
unchanged payload to `/create`. Then claim a body-free envelope:

```bash
curl -fsS "$RELAY_API/claim" \
  -H "Authorization: Bearer $ROBOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"recipient_email":"bob@example.com"}'
```

After the same recipient grants permission, exchange the returned
`message_id` and `claim_token` for the body:

```bash
curl -fsS "$RELAY_API/permission" \
  -H "Authorization: Bearer $ROBOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "relay-20260724-001",
    "claim_token": "<claim-token>",
    "recipient_email": "bob@example.com"
  }'
```

Call `/begin_delivery` and `/complete` with:

```json
{"message_id":"relay-20260724-001","claim_token":"<claim-token>"}
```

Other operations are `decline`, `snooze`, `playback_failure`, and
`sender_statuses`. The request models and response fields are defined in
[`src/tailwag_memory/api/schemas.py`](../src/tailwag_memory/api/schemas.py).
The API derives the robot ID from the bearer token; an
`assigned_robot_id` request field is invalid.

`policy_check` returns `200` with `allowed: false` for a normal policy denial;
the caller must stop. A policy denial during `create` returns `403`. Other
failures use `422` for invalid input, `409` for duplicate IDs or invalid
transitions, and `429` for rate limits. Safety provider timeout,
unavailability, or bad configuration returns `503`; a malformed provider
decision returns `502`.

`GET /health` is dependency-free liveness. `GET /ready` checks robot-token and
OpenAI configuration, Neo4j connectivity, and the required online relay schema.

## Package Example

Direct package consumers use the same lifecycle:

```python
from collections.abc import Callable

from tailwag_memory import RelayMessageInput, TailwagMemoryClient

message = RelayMessageInput(
    id="relay-20260724-001",
    sender_email="alice@example.com",
    recipient_email="bob@example.com",
    body="Please meet me by the reception desk at 3 PM.",
    metadata={"source": "argos"},
)

with TailwagMemoryClient.from_env() as client:
    policy = client.check_relay_policy(message, robot_id="robot-bos3-01")
    if not policy.allowed:
        raise RuntimeError(policy.reason)

# Stop here. Read back policy.recipient_display_name and the exact message.body.
# After the same recognized sender explicitly confirms:
with TailwagMemoryClient.from_env() as client:
    client.create_relay_message(message, robot_id="robot-bos3-01")
    envelope = client.claim_next_relay_envelope(
        recipient_email="bob@example.com",
        robot_id="robot-bos3-01",
    )

# envelope has no body. After the same recognized recipient grants permission,
# the caller can invoke this function with its controlled TTS implementation.
def deliver_after_permission(
    envelope,
    play_exactly: Callable[[str], None],
) -> None:
    with TailwagMemoryClient.from_env() as client:
        released = client.grant_relay_permission(
            envelope.message_id,
            claim_token=envelope.claim_token,
            recipient_email="bob@example.com",
            robot_id="robot-bos3-01",
        )
        if released.body is None:
            raise RuntimeError("permission did not release a body")
        client.begin_relay_delivery(
            envelope.message_id,
            claim_token=envelope.claim_token,
            robot_id="robot-bos3-01",
        )
        play_exactly(released.body)
        client.complete_relay_delivery(
            envelope.message_id,
            claim_token=envelope.claim_token,
            robot_id="robot-bos3-01",
        )
```

Sender confirmation, recipient permission, and the `play_exactly` callback are
caller-owned behavior. On playback failure, call
`record_relay_playback_failure` instead of `complete_relay_delivery`, with
accurate `audio_started` evidence.

## Storage And Retention

```cypher
(sender:Person)-[:SENT_RELAY]->(message:RelayMessage)
(message)-[:FOR_RECIPIENT]->(recipient:Person)
(message)-[:ASSIGNED_TO]->(robot:Robot)
```

`RelayMessage` stores the exact body, identity snapshots, assigned robot,
delivery window, status, claim and playback state, bounded failure details, and
JSON metadata. Schema initialization creates the `relay_message_id` constraint
and the `relay_message_status`, `relay_message_delivery`, and
`relay_message_expires_at` indexes.

Expiry ends delivery eligibility only. It never deletes, redacts, or overwrites
the body. Bodies remain in Neo4j after delivery, decline, failure, or expiry,
and may also exist in transcripts and backups under their independent retention
rules. Tailwag has no relay deletion or body-redaction operation; do not
describe expiry as erasure.

## Verification

Run the complete mock and HTTP contract suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Then use real Neo4j to test concurrent create, claim, and transitions:

```bash
docker compose up -d neo4j
docker compose --profile api up --build api
tailwag schema init
```

Seed two uniquely emailed people and the configured robot. Verify:

- `policy_check` writes nothing and `create` occurs only after explicit sender
  confirmation
- claim and sender-status responses never contain `body`
- only the correct recipient, robot, token, and state release the body
- decline requires no receipt acknowledgement and is visible to the sender
- pre-audio failure returns to pending with sender-visible failure details
- post-audio failure becomes non-replayable `delivery_uncertain`
- sender-specified expiry is honored; default expiry applies when omitted
- expiry never removes or changes the body
- `EXPLAIN`/`PROFILE` selects `relay_message_delivery` for claim and
  `relay_message_status` for maintenance
- adding terminal history does not increase claim or maintenance candidate rows

Mock tests do not prove Neo4j contention behavior. AWS readiness, worker, queue,
and alarm checks are a separate gate documented in
[Message Relay On AWS](message-relay-aws-testing.md). Controlled TTS,
recognition ownership, and the Linux audio path require a real Ubuntu robot
hardware test.
