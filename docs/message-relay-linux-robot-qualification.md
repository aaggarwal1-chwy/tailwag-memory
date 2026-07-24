# Linux And Robot Message Relay Qualification

Use this runbook to qualify one Tailwag revision for Linux, real Neo4j,
concurrency, retained-volume, AWS development, and an Ubuntu robot. It is the
canonical cross-environment relay checklist; the relay contract remains in
[Robot Message Relay](message-relay.md), and deployed maintenance details remain
in [Message Relay On AWS](message-relay-aws-testing.md).

A release passes only when every applicable automated gate passes and a human
operator signs off every manual-only gate. Mock tests do not qualify Neo4j
contention, AWS wiring, recognition, TTS, or physical audio.

## Product Targets

- Pilot and expected fleet: 2 robots, about 30 people, and no more than 10–20
  relay messages per day.
- Recommended latency targets, pending product confirmation: P95 under 1 second
  from sender confirmation to durable create, under 2 seconds from an eligible
  recipient encounter to permission prompt start, and under 2 seconds from
  permission to audio start. Track human/availability wait separately from
  system latency.
- Reuse a signed 120-second attestation for the exact policy-approved payload at
  create time. Create must still revalidate identity, robot assignment, expiry,
  rate limits, and message-ID uniqueness.
- Give the recognized recipient 25 seconds to answer a permission prompt.
  Expiry or shutdown before permission returns the message to `pending` for a
  later offer. Shutdown after audio may have started must remain terminal and
  non-replayable.

## Safety And Evidence Rules

- Use synthetic people and unique `qual-...` IDs for local and AWS data. Use
  only authorized, consenting participants for the robot gate. Every message
  body must be non-sensitive and synthetic.
- Never paste credentials into this document, source control, command
  arguments recorded by shared automation, logs, screenshots, or evidence.
  Read secrets into the current shell or use the approved secret-injection
  path.
- Never capture a relay body in logs. Permission is the only operation allowed
  to return it; compare it in memory and record only pass/fail.
- Do not run qualification against production. AWS commands below target an
  explicitly approved development environment.
- Stop on an unexpected body disclosure, wrong-recipient release, duplicate
  playback, unplanned identity change, robot motion, audio routed to the wrong
  device, or any uncertain credential/account/region. Planned wrong-owner and
  unknown-owner cases below are controlled negative tests.
- Relay expiry is not deletion. Do not purge queues, delete relay records, or
  describe expiry as erasure.

Create a private, temporary evidence directory. Keep only sanitized command
output, timestamps, revision IDs, counts, and pass/fail results:

```bash
cd /path/to/tailwag-memory
export QUAL_RUN_ID="relay-qual-$(date -u +%Y%m%dT%H%M%SZ)"
export QUAL_EVIDENCE_DIR="$(mktemp -d "/tmp/${QUAL_RUN_ID}.XXXXXX")"
set -Eeuo pipefail
test -z "$(git status --porcelain)"
git rev-parse HEAD | tee "$QUAL_EVIDENCE_DIR/tailwag-revision.txt"
date -u +%FT%TZ | tee "$QUAL_EVIDENCE_DIR/started-at.txt"
```

Do not copy tokens, request payloads, permission responses, raw audio, images,
transcripts, or message bodies into that directory.

## 1. Linux Setup And Mock Gate

Prerequisites are Linux, Python 3.10 or newer, Docker with Compose, `curl`,
`jq`, and `openssl`. From a clean checkout:

```bash
cd /path/to/tailwag-memory
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[api,aws]"
docker compose up -d neo4j
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD=tailwag-memory
export TAILWAG_LIVE_NEO4J_TEST_DATABASE=I_UNDERSTAND_THIS_MUTATES_SCHEMA
tailwag schema init
curl -fsS http://localhost:7474 >/dev/null
```

Run the complete mock and HTTP contract suite. Hold raw output only in process
memory and persist only the sanitized result:

```bash
if QUAL_TEST_OUTPUT="$(
  TAILWAG_RUN_LIVE_NEO4J_TESTS=0 \
  TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=0 \
  PYTHONPATH=src python3 -m unittest discover -s tests 2>&1
)"; then
  if ! grep -q '^OK (skipped=21)$' <<<"$QUAL_TEST_OUTPUT"; then
    printf 'FAIL mock-tests unexpected-skip-count\n' \
      | tee "$QUAL_EVIDENCE_DIR/mock-tests.txt"
    unset QUAL_TEST_OUTPUT
    exit 1
  fi
  printf 'PASS mock-tests\n' | tee "$QUAL_EVIDENCE_DIR/mock-tests.txt"
else
  printf 'FAIL mock-tests\n' | tee "$QUAL_EVIDENCE_DIR/mock-tests.txt"
  unset QUAL_TEST_OUTPUT
  exit 1
fi
unset QUAL_TEST_OUTPUT
```

Pass requires zero failures or errors and exactly the 21 gated live-Neo4j
skips. This suite is offline and does not replace the live Neo4j gate.

## 2. Real Neo4j Concurrency And Retained-Volume Gate

The live suite is deliberately opt-in and uses the `NEO4J_*` values above:

```bash
if QUAL_TEST_OUTPUT="$(TAILWAG_RUN_LIVE_NEO4J_TESTS=1 \
  TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=0 \
  TAILWAG_LIVE_NEO4J_TEST_DATABASE=I_UNDERSTAND_THIS_MUTATES_SCHEMA \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=tailwag-memory \
  PYTHONPATH=src python3 -m unittest -v \
    tests.test_relay_live_neo4j \
    tests.test_relay_preaudio_live_neo4j 2>&1)"; then
  if ! grep -q '^OK (skipped=2)$' <<<"$QUAL_TEST_OUTPUT"; then
    printf 'FAIL live-neo4j-tests unexpected-skip-count\n' \
      | tee "$QUAL_EVIDENCE_DIR/live-neo4j-tests.txt"
    unset QUAL_TEST_OUTPUT
    exit 1
  fi
  printf 'PASS live-neo4j-tests\n' \
    | tee "$QUAL_EVIDENCE_DIR/live-neo4j-tests.txt"
else
  printf 'FAIL live-neo4j-tests\n' \
    | tee "$QUAL_EVIDENCE_DIR/live-neo4j-tests.txt"
  unset QUAL_TEST_OUTPUT
  exit 1
fi
unset QUAL_TEST_OUTPUT
```

Pass requires the primary cases to run with zero failures or errors and exactly
two skips: the claim and maintenance retained-volume cases enabled by the
separate load command below.
The passing suite covers:

- concurrent creates cannot bypass the daily sender limit, active
  sender-recipient limit, or unique message IDs
- concurrent claims release at most one body-free envelope to the assigned
  robot and intended recipient
- concurrent permission and decline transitions have one winner; stale tokens,
  wrong robots, wrong recipients, archived identities, and expiry cannot
  release the body
- grant-versus-release, begin-versus-release, and
  begin-versus-pre-audio-failure races preserve one-winner CAS behavior and
  return the message to `pending` without removing its body
- begin, complete, and both playback-failure branches preserve lifecycle,
  retention, and replay-safety invariants
- `audio_started=false` returns a failed playback to `pending`, while
  `audio_started=true` ends in non-replayable `delivery_uncertain`
- maintenance is idempotent and correctly expires messages, releases abandoned
  pre-playback claims, marks stale delivery uncertain, and leaves controls
  unchanged
- claim and maintenance candidate counts stay bounded after terminal history is
  added, and the expected relay indexes are selected at representative retained
  volume
- body retention and replay safety hold through both playback-failure branches

Run the separately gated retained-terminal-volume comparison. The default 250
fixtures is appropriate for a development gate; the configurable bound is
1 through 5000. The test compares profiled candidate rows and database hits,
not noisy wall-clock timing:

```bash
if QUAL_TEST_OUTPUT="$(TAILWAG_RUN_LIVE_NEO4J_TESTS=1 \
  TAILWAG_RUN_LIVE_NEO4J_VOLUME_TESTS=1 \
  TAILWAG_LIVE_NEO4J_TEST_DATABASE=I_UNDERSTAND_THIS_MUTATES_SCHEMA \
  TAILWAG_LIVE_NEO4J_TERMINAL_VOLUME=250 \
  NEO4J_URI=bolt://localhost:7687 \
  NEO4J_USER=neo4j \
  NEO4J_PASSWORD=tailwag-memory \
  PYTHONPATH=src python3 -m unittest -v \
    tests.test_relay_live_neo4j \
    tests.test_relay_preaudio_live_neo4j 2>&1)"; then
  if ! grep -q '^OK$' <<<"$QUAL_TEST_OUTPUT"; then
    printf 'FAIL live-neo4j-volume unexpected-skip-count\n' \
      | tee "$QUAL_EVIDENCE_DIR/live-neo4j-volume.txt"
    unset QUAL_TEST_OUTPUT
    exit 1
  fi
  printf 'PASS live-neo4j-volume\n' \
    | tee "$QUAL_EVIDENCE_DIR/live-neo4j-volume.txt"
else
  printf 'FAIL live-neo4j-volume\n' \
    | tee "$QUAL_EVIDENCE_DIR/live-neo4j-volume.txt"
  unset QUAL_TEST_OUTPUT
  exit 1
fi
unset QUAL_TEST_OUTPUT
```

Pass requires zero failures, errors, or skips. Terminal fixtures must not enter
the pending candidate set, and database hits must not materially increase.

Record the Neo4j version without exporting graph contents:

```bash
docker compose exec -T -e NEO4J_USERNAME -e NEO4J_PASSWORD \
  neo4j cypher-shell \
  'CALL dbms.components() YIELD name, versions RETURN name, versions' \
  | tee "$QUAL_EVIDENCE_DIR/neo4j-version.txt"
```

## 3. Local HTTP And Data Gate

The HTTP smoke test calls the real OpenAI relay-policy boundary and may incur
cost. It is an explicit operator-approved gate. In one shell, create an
ephemeral robot credential and read the OpenAI key without echoing it:

```bash
cd /path/to/tailwag-memory
source .venv/bin/activate
set -Eeuo pipefail
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD=tailwag-memory
export QUAL_DATA_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
export QUAL_ROBOT_ID="robot-linux-qual-$QUAL_DATA_SUFFIX"
export QUAL_SENDER_ID="person-relay-sender-$QUAL_DATA_SUFFIX"
export QUAL_RECIPIENT_ID="person-relay-recipient-$QUAL_DATA_SUFFIX"
export QUAL_SENDER_EMAIL="relay.sender.$QUAL_DATA_SUFFIX@example.invalid"
export QUAL_RECIPIENT_EMAIL="relay.recipient.$QUAL_DATA_SUFFIX@example.invalid"
set +x
export ROBOT_TOKEN="$(openssl rand -hex 32)"
export TAILWAG_ROBOT_API_TOKENS_JSON="{\"$QUAL_ROBOT_ID\":\"$ROBOT_TOKEN\"}"
export TAILWAG_RELAY_ATTESTATION_SECRET="$(openssl rand -hex 32)"
export TAILWAG_RELAY_ATTESTATION_KEY_ID="linux-qual-$QUAL_DATA_SUFFIX"
read -rsp "OpenAI API key: " OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
cleanup_relay_server_secrets() {
  unset ROBOT_TOKEN TAILWAG_ROBOT_API_TOKENS_JSON OPENAI_API_KEY
  unset TAILWAG_RELAY_ATTESTATION_SECRET TAILWAG_RELAY_ATTESTATION_KEY_ID
}
trap cleanup_relay_server_secrets EXIT INT TERM
```

Seed exactly two active people and the assigned narrow robot. This does not
create a relay message:

```bash
docker compose exec -T -e NEO4J_USERNAME -e NEO4J_PASSWORD \
  neo4j cypher-shell \
  -P "sender_id => '$QUAL_SENDER_ID'" \
  -P "recipient_id => '$QUAL_RECIPIENT_ID'" \
  -P "sender_email => '$QUAL_SENDER_EMAIL'" \
  -P "recipient_email => '$QUAL_RECIPIENT_EMAIL'" \
  -P "robot_id => '$QUAL_ROBOT_ID'" \
  'MERGE (s:Person {id:$sender_id})
   SET s.email=$sender_email, s.display_name="Relay Sender Qual", s.status="active"
   MERGE (r:Person {id:$recipient_id})
   SET r.email=$recipient_email, r.display_name="Relay Recipient Qual", r.status="active"
   MERGE (robot:Robot {id:$robot_id})
   SET robot.display_name="Linux Qualification Robot"
   RETURN s.id AS sender, r.id AS recipient, robot.id AS robot'
printf 'Reuse this non-secret data suffix in shell 2: %s\n' "$QUAL_DATA_SUFFIX"
```

Start the API in this same configured shell and leave it running:

```bash
python3 -m uvicorn tailwag_memory.api.app:create_app \
  --factory --host 127.0.0.1 --port 8000
```

In a second shell, export the same non-secret IDs and obtain `ROBOT_TOKEN`
through the approved local handoff without printing it:

```bash
cd /path/to/tailwag-memory
set -Eeuo pipefail
export TAILWAG_URL=http://127.0.0.1:8000
export RELAY_API="$TAILWAG_URL/argos/providers/message-relay/resources/messages/request"
export NEO4J_USER=neo4j
export NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD=tailwag-memory
read -rp "Data suffix printed by shell 1: " QUAL_DATA_SUFFIX
export QUAL_DATA_SUFFIX
export QUAL_SENDER_EMAIL="relay.sender.$QUAL_DATA_SUFFIX@example.invalid"
export QUAL_RECIPIENT_EMAIL="relay.recipient.$QUAL_DATA_SUFFIX@example.invalid"
set +x
read -rsp "Robot bearer token: " ROBOT_TOKEN
printf '\n'
export ROBOT_TOKEN
cleanup_relay_qual_secrets() {
  unset ROBOT_TOKEN QUAL_MESSAGE_JSON QUAL_CREATE_JSON QUAL_MESSAGE_BODY
  unset POLICY_ATTESTATION POLICY_ATTESTATION_EXPIRES_AT CLAIM_TOKEN
}
trap cleanup_relay_qual_secrets EXIT INT TERM
curl -fsS "$TAILWAG_URL/health" | jq -e '.status == "ok"'
curl -fsS "$TAILWAG_URL/ready" | jq -e '.status == "ready" and .relay == true'
```

Define a local HTTP helper that reads the token from the environment and the
JSON body from standard input. Neither value appears in process arguments:

```bash
relay_post() {
  RELAY_OPERATION="$1" python3 -c '
import os
import sys
import urllib.request

url = (
    os.environ["RELAY_API"].rstrip("/")
    + "/"
    + os.environ["RELAY_OPERATION"].strip("/")
)
request = urllib.request.Request(
    url,
    data=sys.stdin.buffer.read(),
    headers={
        "Authorization": "Bearer " + os.environ["ROBOT_TOKEN"],
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=45) as response:
    sys.stdout.buffer.write(response.read())
'
}
```

Build one synthetic request in memory. Do not redirect or `tee` it:

```bash
export QUAL_MESSAGE_ID="qual-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
export QUAL_MESSAGE_BODY="Synthetic qualification message. Meet at reception at 3 PM."
export QUAL_MESSAGE_JSON="$(
  python3 -c '
import json
import os

print(json.dumps({"message": {
    "id": os.environ["QUAL_MESSAGE_ID"],
    "sender_email": os.environ["QUAL_SENDER_EMAIL"],
    "recipient_email": os.environ["QUAL_RECIPIENT_EMAIL"],
    "body": os.environ["QUAL_MESSAGE_BODY"],
    "metadata": {"source": "linux-qualification"},
}}))
'
 )"
test "$(
  docker compose exec -T -e NEO4J_USERNAME -e NEO4J_PASSWORD \
    neo4j cypher-shell \
    -P "message_id => '$QUAL_MESSAGE_ID'" \
    'MATCH (m:RelayMessage {id:$message_id}) RETURN count(m)' \
    | tail -n 1 | tr -d '\r'
)" = "0"
POLICY_RESPONSE="$(
  printf '%s' "$QUAL_MESSAGE_JSON" | relay_post policy_check
)"
jq -e \
  --arg sender "$QUAL_SENDER_EMAIL" \
  --arg recipient "$QUAL_RECIPIENT_EMAIL" \
  '.allowed == true
   and .sender_email == $sender
   and .recipient_email == $recipient
   and (.policy_attestation | length > 0)
   and (.policy_attestation_expires_at | length > 0)
   and has("body") == false' \
  <<<"$POLICY_RESPONSE"
export POLICY_ATTESTATION="$(jq -r '.policy_attestation' <<<"$POLICY_RESPONSE")"
export POLICY_ATTESTATION_EXPIRES_AT="$(
  jq -r '.policy_attestation_expires_at' <<<"$POLICY_RESPONSE"
)"
test "$(
  docker compose exec -T -e NEO4J_USERNAME -e NEO4J_PASSWORD \
    neo4j cypher-shell \
    -P "message_id => '$QUAL_MESSAGE_ID'" \
    'MATCH (m:RelayMessage {id:$message_id}) RETURN count(m)' \
    | tail -n 1 | tr -d '\r'
)" = "0"
```

`policy_check` must write nothing. The operator must now render the canonical
recipient and exact `QUAL_MESSAGE_BODY`, compare the readback, and explicitly
confirm. This is a **manual-only API gate**; direct HTTP cannot qualify
recognition continuity, and `policy_check` and `create` must not be combined in
automation:

```bash
read -r -p "After exact readback, type CONFIRM-SEND: " QUAL_CONFIRM
test "$QUAL_CONFIRM" = "CONFIRM-SEND"
python3 -c '
from datetime import datetime, timezone
import os

expiry = datetime.fromisoformat(os.environ["POLICY_ATTESTATION_EXPIRES_AT"])
if datetime.now(timezone.utc) > expiry:
    raise SystemExit("policy attestation expired; repeat policy check and readback")
'
export QUAL_CREATE_JSON="$(
  printf '%s' "$QUAL_MESSAGE_JSON" | python3 -c '
import json
import os
import sys

payload = json.load(sys.stdin)
payload["policy_attestation"] = os.environ["POLICY_ATTESTATION"]
print(json.dumps(payload))
'
)"
CREATE_RESPONSE="$(
  printf '%s' "$QUAL_CREATE_JSON" | relay_post create
)"
jq -e \
  --arg id "$QUAL_MESSAGE_ID" \
  '.message_id == $id and .status == "pending" and has("body") == false' \
  <<<"$CREATE_RESPONSE"
unset POLICY_ATTESTATION POLICY_ATTESTATION_EXPIRES_AT QUAL_CREATE_JSON
```

Claim the body-free envelope:

```bash
CLAIM_RESPONSE="$(
  jq -nc --arg email "$QUAL_RECIPIENT_EMAIL" \
    '{recipient_email:$email}' \
    | relay_post claim
)"
jq -e \
  --arg id "$QUAL_MESSAGE_ID" \
  '.message_id == $id
   and .status == "claimed"
   and (.claim_token | length > 0)
   and has("body") == false' \
  <<<"$CLAIM_RESPONSE"
export CLAIM_TOKEN="$(jq -r '.claim_token' <<<"$CLAIM_RESPONSE")"
```

The operator must explicitly authorize this synthetic recipient transition.
This is another **manual-only API gate**; direct HTTP cannot qualify recipient
recognition. Permission is the first response allowed to contain a body:

```bash
read -r -p "After same-recipient permission, type PERMIT-READ: " QUAL_PERMISSION
test "$QUAL_PERMISSION" = "PERMIT-READ"
PERMISSION_RESPONSE="$(
  python3 -c '
import json
import os

print(json.dumps({
    "message_id": os.environ["QUAL_MESSAGE_ID"],
    "claim_token": os.environ["CLAIM_TOKEN"],
    "recipient_email": os.environ["QUAL_RECIPIENT_EMAIL"],
}))
' \
    | relay_post permission
)"
printf '%s' "$PERMISSION_RESPONSE" | python3 -c '
import json
import os
import sys

response = json.load(sys.stdin)
if (
    response.get("status") != "permission_granted"
    or response.get("body") != os.environ["QUAL_MESSAGE_BODY"]
):
    raise SystemExit("permission response did not contain the exact body")
'
printf 'PASS: permission released the exact in-memory body\n'
unset POLICY_RESPONSE CREATE_RESPONSE CLAIM_RESPONSE PERMISSION_RESPONSE
unset QUAL_MESSAGE_JSON QUAL_MESSAGE_BODY CLAIM_TOKEN ROBOT_TOKEN OPENAI_API_KEY
```

Do not call `begin_delivery` or `complete` in this API-only smoke. Those
operations are qualified with real playback in the robot gate. Stop the local
API, unset `ROBOT_TOKEN`, `TAILWAG_ROBOT_API_TOKENS_JSON`, and `OPENAI_API_KEY`
in shell 1, and do not treat the synthetic message's expiry as deletion.

## 4. AWS Development Gate

AWS inspection is read-only until the operator has confirmed the intended
account, role, `AWS_REGION`, resource prefix, and authorization. Capture only
sanitized output:

```bash
set -Eeuo pipefail
export AWS_REGION="${AWS_REGION:-$(aws configure get region)}"
test -n "$AWS_REGION"
read -r -p "Approved development resource prefix: " AWS_RESOURCE_PREFIX
test -n "$AWS_RESOURCE_PREFIX"
export AWS_RESOURCE_PREFIX
aws sts get-caller-identity \
  --region "$AWS_REGION" \
  --query '{Account:Account,Arn:Arn}' --output json \
  | tee "$QUAL_EVIDENCE_DIR/aws-identity.json"
printf '%s\n' "$AWS_REGION" | tee "$QUAL_EVIDENCE_DIR/aws-region.txt"
printf '%s\n' "$AWS_RESOURCE_PREFIX" \
  | tee "$QUAL_EVIDENCE_DIR/aws-resource-prefix.txt"
for QUAL_TEMPLATE in deploy/aws/cloudformation/*.yaml; do
  aws cloudformation validate-template \
    --region "$AWS_REGION" \
    --template-body "file://$QUAL_TEMPLATE" \
    --query 'Description' --output text >/dev/null
done
printf 'PASS cloudformation-validation\n' \
  | tee "$QUAL_EVIDENCE_DIR/cloudformation-validation.txt"
unset QUAL_TEMPLATE
```

Follow [Message Relay On AWS](message-relay-aws-testing.md) end to end. Pass
requires:

- relay schema and indexes are online and representative `EXPLAIN`/`PROFILE`
  uses the claim and maintenance indexes
- ECS runs the intended immutable revision, `/health` and `/ready` pass, and
  each robot has a distinct secret-injected token
- an authenticated `sender_statuses` smoke succeeds without a body
- the intended memory Lambda and SQS event source are active; the queue drains,
  the DLQ stays empty, and the unique maintenance job reaches `succeeded` with
  all three result counts
- worker, queue-age, and DLQ alarms exist, have actions enabled, and are not in
  `ALARM`
- synthetic expired, abandoned, stale-delivering, and control records change
  exactly as expected, with no body logged, altered, or deleted

Sending a smoke job, changing secrets, deploying artifacts, enabling the
schedule, or rolling back is a **manual-only, separately authorized gate**.
Create or update the relay schedule disabled-first and enable it only after the
manual smoke and alarm checks pass. Never purge the shared queue.

## 5. Ubuntu Robot Gate

Use the Argos checkout and its `docs/message_relay.md` and `docs/launch.md` on
the Ubuntu robot. The active manifest must expose identity memory and
`memory.message_relay`; the robot relay token must be distinct from the Tailwag
administrative token.

Before launch:

```bash
cd /path/to/argos-agent
set -Eeuo pipefail
poetry install
source setup_shell.sh
python3 -m pip install --no-deps -r argos_src/face_recognition/requirements.txt
python3 -B -m pytest \
  tests/argos_src/message_relay \
  tests/argos_src/provider_api \
  tests/argos_src/test_argos_profile_config.py \
  tests/argos_src/tools/test_tool_ids.py
```

The profile test must prove that the selected qualification manifest's primary
robot advertises no capabilities, the profile exposes only the three relay
tools, and battery subscriptions are disabled. Treat any motion, posture,
embodiment, patrol, gesture, owner-turn, proactive-greeting, or battery
capability as a failed preflight. Manifest capabilities remove model-visible
actions; they are not a runtime provider ACL.

Read the three runtime secrets into the launch shell without echoing them, then
check Tailwag before starting Argos:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY; printf '\n'
read -rsp "Tailwag admin token: " TAILWAG_API_BEARER_TOKEN; printf '\n'
read -rsp "Tailwag robot token: " TAILWAG_ROBOT_API_BEARER_TOKEN; printf '\n'
export OPENAI_API_KEY TAILWAG_API_BEARER_TOKEN TAILWAG_ROBOT_API_BEARER_TOKEN
export TAILWAG_BASE_URL="https://<approved-development-api-host>"
curl -fsS "${TAILWAG_BASE_URL%/}/health" | jq -e '.status == "ok"'
curl -fsS "${TAILWAG_BASE_URL%/}/ready" | jq -e '.status == "ready"'
read -r -p \
  "After engaging the provider actuator inhibit and verifying an independent physical stop, type ACTUATORS-DENIED: " \
  QUAL_ACTUATOR_CONFIRM
test "$QUAL_ACTUATOR_CONFIRM" = "ACTUATORS-DENIED"
python3 run_profile.py --profile message_relay_qualification
```

The qualification profile exposes only the three relay tools and disables
display, patrol, gestures, owner-turn rotation, and proactive greetings. Its
qualification manifest advertises no primary-robot capabilities. The external
provider inhibit is the mandatory enforcement boundary for non-tool base
events. An independent physical E-stop or safe power-removal path must remain
reachable in case that inhibit fails. Without both controls, do not launch.

The following checks are **manual-only** because automated tests cannot prove
recognition continuity, permission intent, TTS fidelity, audio drain, or
physical safety:

1. Before participants approach, rehearse both hazard-specific abort paths with
   two operators when available. For unexpected speech, wrong-device audio, or
   a privacy hazard, immediately mute the output with
   `wpctl set-mute @DEFAULT_AUDIO_SINK@ 1`; for unexpected motion, immediately
   use the independent physical E-stop or safe power-removal path. Then press
   `Ctrl-C` in Argos, apply the other safeguard, and verify physical audio
   drain, silence, and no queued speech. Reset neither safeguard until the cause
   is understood.
   Confirm clear space, safe battery state, correct microphone and speaker, and
   operator approval before bring-up.
2. Have an authorized, consenting, uniquely recognized test participant prepare
   a non-sensitive synthetic message.
   Confirm the robot reads back the canonical recipient and exact body, then
   accepts confirmation only in a later turn from the same continuously
   recognized owner.
3. Verify owner change or unknown ownership before readback or confirmation
   invalidates the send. There is no one-call send.
4. Have the intended recipient receive a body-free prompt and explicitly
   permit delivery. Verify owner change, unknown ownership, ambiguous speech,
   and the wrong person never release or speak the body.
5. Let one prompt exceed 25 seconds without a permission response. Verify the
   body is not released, the message returns to `pending`, and a later encounter
   offers it again.
6. Verify controlled TTS speaks the permitted body exactly once and unchanged;
   `begin_delivery` occurs immediately before playback and `complete` only
   after physical audio drain. Confirm there is no receipt prompt.
7. Interrupt before audio starts and confirm the message returns to `pending`
   with sender-visible failure details. Interrupt after audio starts and confirm
   terminal `delivery_uncertain` with no automatic replay.
8. Repeat with decline, one-message-at-a-time permission, sender status,
   sender-specified expiry, and default expiry. No pre-permission or status
   response may contain the body.
9. Check Argos owner-epoch and playback logs without recording the body. Confirm
   shutdown and owner changes leave no queued speech that can play for the next
   person.

A planned post-audio interruption passes only when it produces the expected
terminal `delivery_uncertain` state with no replay. Any unplanned uncertainty,
wrong-person release, altered speech, repeated speech, or missing failure
report is a failure, not an acceptable retry.

## Final Pass/Fail Record

Record `PASS`, `FAIL`, or `NOT RUN`, an operator, UTC time, and a sanitized
evidence reference for each row:

| Gate | Pass condition |
| --- | --- |
| Tailwag revision | Intended immutable revision recorded |
| Mock/HTTP contracts | Full unittest discovery has zero failures/errors |
| Live Neo4j | Primary run passes with only the documented volume skip; volume run passes without skips |
| Contention | Create, claim, and transition races preserve limits and CAS |
| Retained volume | Candidate counts remain bounded and expected indexes are used |
| Local HTTP | Health/readiness, policy, confirmed create, body-free claim, and exact permission pass |
| AWS development | Readiness, worker, queue, DLQ, idempotency, maintenance, and alarms pass |
| Latency | P95 targets pass with at least 20 sanitized pilot observations |
| Argos regressions | Focused Argos suite passes on Ubuntu |
| Sender safety | Same-owner exact readback and later-turn confirmation pass |
| Recipient safety | Same-owner permission is required before body release |
| Playback | Exact TTS, audio drain, interruption, and failure evidence pass |
| Privacy/retention | No secret/body evidence leak; expiry is not represented as deletion |

The overall result is `FAIL` if any required row fails or any manual-only robot
gate is unobserved. `NOT RUN` is acceptable only for a clearly scoped
pre-qualification report; it is not release approval.
