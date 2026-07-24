from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import unittest

from tailwag_memory import relay_policy_attestation as attestation_module
from tailwag_memory.models import RelayMessageInput
from tailwag_memory.relay_policy_attestation import (
    ATTESTATION_TTL_SECONDS,
    MAX_CLOCK_SKEW_SECONDS,
    RelayPolicyAttestationError,
    RelayPolicyAttestor,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
SECRET = "test-relay-attestation-secret-32-bytes-minimum"
IDENTITIES = {
    "sender_person_id": "person-alice",
    "recipient_person_id": "person-bob",
    "sender_email": "alice@example.com",
    "recipient_email": "bob@example.com",
}


class RelayPolicyAttestationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = NOW
        self.attestor = RelayPolicyAttestor(
            secret=SECRET,
            key_id="test-key-1",
            policy_model="gpt-test-relay-policy",
            clock=lambda: self.now,
        )
        self.message = RelayMessageInput(
            id="relay-1",
            sender_email="Alice@Example.com",
            recipient_email="Bob@Example.com",
            body="Keep  TWO spaces exactly.",
            metadata={"source": "argos", "sequence": 1},
        )

    def test_round_trip_has_fixed_lifetime_and_no_message_body_claim(self) -> None:
        token, expires_at = self.attestor.issue(
            self.message,
            robot_id="robot-1",
            identities=IDENTITIES,
        )

        claims = self.attestor.verify(
            token,
            self.message,
            robot_id="robot-1",
            identities=IDENTITIES,
        )

        self.assertEqual(
            claims.payload_digest,
            self.attestor.payload_fingerprint(self.message),
        )
        self.assertEqual(claims.expires_at, expires_at)
        self.assertEqual(
            datetime.fromisoformat(expires_at),
            NOW + timedelta(seconds=ATTESTATION_TTL_SECONDS),
        )
        encoded_claims = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(
            encoded_claims + "=" * (-len(encoded_claims) % 4)
        )
        token_claims = json.loads(decoded)
        self.assertNotIn("body", token_claims)
        self.assertNotIn(self.message.body, token)
        self.assertEqual(token_claims["iss"], "tailwag-memory")
        self.assertEqual(token_claims["aud"], "relay-message-create")
        self.assertTrue(token_claims["allowed"])
        self.assertEqual(token_claims["policy_model"], "gpt-test-relay-policy")

    def test_predictable_body_fingerprint_is_keyed(self) -> None:
        other_attestor = RelayPolicyAttestor(
            secret="different-attestation-secret-32-bytes-minimum",
            key_id="other-key",
            policy_model="gpt-test-relay-policy",
            clock=lambda: self.now,
        )

        first = self.attestor.payload_fingerprint(self.message)
        second = other_attestor.payload_fingerprint(self.message)
        unkeyed = hashlib.sha256(
            attestation_module._relay_payload_bytes(self.message)
        ).hexdigest()

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, unkeyed)
        self.assertNotEqual(second, unkeyed)
        self.assertEqual(len(first), 64)
        self.assertEqual(len(second), 64)

    def test_exact_payload_fields_and_omission_markers_are_bound(self) -> None:
        token, _ = self.attestor.issue(
            self.message,
            robot_id="robot-1",
            identities=IDENTITIES,
        )
        mutations = (
            replace(self.message, id="relay-2"),
            replace(self.message, sender_email="alice@example.com"),
            replace(self.message, recipient_email="bob+other@example.com"),
            replace(self.message, body="Keep TWO spaces exactly."),
            replace(self.message, deliver_after=NOW.isoformat()),
            replace(
                self.message,
                expires_at=(NOW + timedelta(days=1)).isoformat(),
            ),
            replace(self.message, metadata={"source": "argos", "sequence": 2}),
        )

        for changed in mutations:
            with self.subTest(changed=changed):
                with self.assertRaises(RelayPolicyAttestationError):
                    self.attestor.verify(
                        token,
                        changed,
                        robot_id="robot-1",
                        identities=IDENTITIES,
                    )

    def test_robot_identity_and_expiry_are_bound(self) -> None:
        token, _ = self.attestor.issue(
            self.message,
            robot_id="robot-1",
            identities=IDENTITIES,
        )
        with self.assertRaises(RelayPolicyAttestationError):
            self.attestor.verify(
                token,
                self.message,
                robot_id="robot-2",
                identities=IDENTITIES,
            )
        changed_identities = {**IDENTITIES, "recipient_person_id": "person-charlie"}
        with self.assertRaises(RelayPolicyAttestationError):
            self.attestor.verify(
                token,
                self.message,
                robot_id="robot-1",
                identities=changed_identities,
            )

        self.now += timedelta(
            seconds=ATTESTATION_TTL_SECONDS + MAX_CLOCK_SKEW_SECONDS + 1
        )
        with self.assertRaises(RelayPolicyAttestationError):
            self.attestor.verify(
                token,
                self.message,
                robot_id="robot-1",
                identities=IDENTITIES,
            )

    def test_signature_tamper_fails_closed(self) -> None:
        token, _ = self.attestor.issue(
            self.message,
            robot_id="robot-1",
            identities=IDENTITIES,
        )
        prefix, claims, signature = token.split(".")
        signature_bytes = bytearray(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        )
        signature_bytes[0] ^= 1
        tampered_signature = base64.urlsafe_b64encode(signature_bytes).rstrip(b"=").decode()
        tampered = f"{prefix}.{claims}.{tampered_signature}"

        with self.assertRaises(RelayPolicyAttestationError):
            self.attestor.verify(
                tampered,
                self.message,
                robot_id="robot-1",
                identities=IDENTITIES,
            )

    def test_secret_must_be_high_entropy_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 32"):
            RelayPolicyAttestor(
                secret="too-short",
                key_id="key-1",
                policy_model="gpt-test",
            )

    def test_oversized_token_is_rejected_before_decode(self) -> None:
        with self.assertRaises(RelayPolicyAttestationError):
            self.attestor.verify(
                "x" * 4097,
                self.message,
                robot_id="robot-1",
                identities=IDENTITIES,
            )

    def test_unicode_claims_round_trip(self) -> None:
        attestor = RelayPolicyAttestor(
            secret=SECRET,
            key_id="clé-signature-一",
            policy_model="gpt-test-relay-policy",
            clock=lambda: self.now,
        )
        message = replace(
            self.message,
            sender_email="álîçé@example.com",
            recipient_email="ボブ@example.com",
        )
        identities = {
            "sender_person_id": "person-álîçé",
            "recipient_person_id": "person-ボブ",
            "sender_email": "álîçé@example.com",
            "recipient_email": "ボブ@example.com",
        }
        token, _ = attestor.issue(
            message,
            robot_id="robot-机器人",
            identities=identities,
        )

        claims = attestor.verify(
            token,
            message,
            robot_id="robot-机器人",
            identities=identities,
        )

        self.assertEqual(claims.payload_digest, attestor.payload_fingerprint(message))


if __name__ == "__main__":
    unittest.main()
