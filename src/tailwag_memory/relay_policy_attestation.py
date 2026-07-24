"""Short-lived proof that relay policy screened one exact caller payload."""

from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Callable, Mapping
from uuid import uuid4

from .models import RelayMessageInput


POLICY_REVISION = "relay-workplace-v1"
ATTESTATION_TTL_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 5
MAX_TOKEN_CHARACTERS = 4096
_TOKEN_PREFIX = "rpa1"
_OMITTED_TIME = {"omitted": True}
_ISSUER = "tailwag-memory"
_AUDIENCE = "relay-message-create"


class RelayPolicyAttestationError(ValueError):
    """A supplied relay policy attestation is invalid or no longer usable."""


@dataclass(frozen=True)
class RelayPolicyAttestationClaims:
    """Verified server-owned claims needed by the relay create path."""

    jti: str
    payload_digest: str
    expires_at: str


class RelayPolicyAttestor:
    """Issue and verify compact HMAC-SHA256 relay policy attestations."""

    def __init__(
        self,
        *,
        secret: str,
        key_id: str,
        policy_model: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        secret_bytes = str(secret or "").encode("utf-8")
        if len(secret_bytes) < 32:
            raise ValueError(
                "TAILWAG_RELAY_ATTESTATION_SECRET must contain at least 32 UTF-8 bytes"
            )
        rendered_key_id = str(key_id or "").strip()
        if not rendered_key_id:
            raise ValueError("TAILWAG_RELAY_ATTESTATION_KEY_ID is required")
        if len(rendered_key_id) > 128:
            raise ValueError(
                "TAILWAG_RELAY_ATTESTATION_KEY_ID must contain at most 128 characters"
            )
        rendered_policy_model = str(policy_model or "").strip()
        if not rendered_policy_model:
            raise ValueError("relay policy model is required for attestation")
        self._secret = secret_bytes
        self._key_id = rendered_key_id
        self._policy_model = rendered_policy_model
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(
        self,
        message: RelayMessageInput,
        *,
        robot_id: str,
        identities: Mapping[str, str],
    ) -> tuple[str, str]:
        """Return an opaque token and its caller-visible UTC expiry."""
        issued_at = int(_utc_datetime(self._clock()).timestamp())
        expires_at = issued_at + ATTESTATION_TTL_SECONDS
        claims = {
            "allowed": True,
            "aud": _AUDIENCE,
            "exp": expires_at,
            "iat": issued_at,
            "iss": _ISSUER,
            "jti": str(uuid4()),
            "kid": self._key_id,
            "payload_digest": self.payload_fingerprint(message),
            "policy_model": self._policy_model,
            "policy_revision": POLICY_REVISION,
            "recipient_email": str(identities["recipient_email"]),
            "recipient_person_id": str(identities["recipient_person_id"]),
            "robot_id": str(robot_id),
            "sender_email": str(identities["sender_email"]),
            "sender_person_id": str(identities["sender_person_id"]),
        }
        encoded_claims = _encode_json(claims)
        signature = hmac.new(
            self._secret,
            encoded_claims.encode("ascii"),
            hashlib.sha256,
        ).digest()
        token = f"{_TOKEN_PREFIX}.{encoded_claims}.{_encode_bytes(signature)}"
        if len(token) > MAX_TOKEN_CHARACTERS:
            raise ValueError("relay policy attestation claims exceed the safe token size")
        expiry = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
        return token, expiry

    def verify(
        self,
        token: str,
        message: RelayMessageInput,
        *,
        robot_id: str,
        identities: Mapping[str, str],
    ) -> RelayPolicyAttestationClaims:
        """Verify signature, lifetime, payload, robot, and canonical identities."""
        try:
            rendered_token = str(token)
            if len(rendered_token) > MAX_TOKEN_CHARACTERS:
                raise ValueError("token is too long")
            prefix, encoded_claims, encoded_signature = rendered_token.split(".")
            if prefix != _TOKEN_PREFIX:
                raise ValueError("wrong token prefix")
            signature = _decode_bytes(encoded_signature)
            if len(signature) != hashlib.sha256().digest_size:
                raise ValueError("invalid signature length")
            expected_signature = hmac.new(
                self._secret,
                encoded_claims.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("signature mismatch")
            claims = json.loads(_decode_bytes(encoded_claims).decode("utf-8"))
            if not isinstance(claims, dict):
                raise ValueError("claims must be an object")
            self._verify_claims(
                claims,
                message=message,
                robot_id=robot_id,
                identities=identities,
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RelayPolicyAttestationError(
                "relay policy attestation is invalid or expired"
            ) from exc
        return RelayPolicyAttestationClaims(
            jti=str(claims["jti"]),
            payload_digest=str(claims["payload_digest"]),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), timezone.utc).isoformat(),
        )

    def payload_fingerprint(self, message: RelayMessageInput) -> str:
        """Return a keyed fingerprint of the exact caller payload."""
        return hmac.new(
            self._secret,
            _relay_payload_bytes(message),
            hashlib.sha256,
        ).hexdigest()

    def _verify_claims(
        self,
        claims: dict[str, object],
        *,
        message: RelayMessageInput,
        robot_id: str,
        identities: Mapping[str, str],
    ) -> None:
        required_string_claims = {
            "jti",
            "kid",
            "aud",
            "iss",
            "payload_digest",
            "policy_model",
            "policy_revision",
            "recipient_email",
            "recipient_person_id",
            "robot_id",
            "sender_email",
            "sender_person_id",
        }
        if any(
            not isinstance(claims.get(name), str) or not str(claims[name])
            for name in required_string_claims
        ):
            raise ValueError("missing string claim")
        if not isinstance(claims.get("iat"), int) or isinstance(claims.get("iat"), bool):
            raise ValueError("invalid issued-at claim")
        if not isinstance(claims.get("exp"), int) or isinstance(claims.get("exp"), bool):
            raise ValueError("invalid expiry claim")
        if claims.get("allowed") is not True:
            raise ValueError("policy was not allowed")

        issued_at = int(claims["iat"])
        expires_at = int(claims["exp"])
        now = int(_utc_datetime(self._clock()).timestamp())
        if expires_at - issued_at != ATTESTATION_TTL_SECONDS:
            raise ValueError("invalid lifetime")
        if issued_at > now + MAX_CLOCK_SKEW_SECONDS:
            raise ValueError("issued in the future")
        if now > expires_at + MAX_CLOCK_SKEW_SECONDS:
            raise ValueError("expired")

        expected_strings = {
            "aud": _AUDIENCE,
            "iss": _ISSUER,
            "kid": self._key_id,
            "payload_digest": self.payload_fingerprint(message),
            "policy_model": self._policy_model,
            "policy_revision": POLICY_REVISION,
            "recipient_email": str(identities["recipient_email"]),
            "recipient_person_id": str(identities["recipient_person_id"]),
            "robot_id": str(robot_id),
            "sender_email": str(identities["sender_email"]),
            "sender_person_id": str(identities["sender_person_id"]),
        }
        for name, expected in expected_strings.items():
            if not _constant_time_text_equal(str(claims[name]), expected):
                raise ValueError(f"{name} mismatch")


def _relay_payload_bytes(message: RelayMessageInput) -> bytes:
    """Canonicalize the exact payload, retaining markers for defaulted times."""
    payload = {
        "body": message.body,
        "deliver_after": (
            _OMITTED_TIME if message.deliver_after == "" else {"value": message.deliver_after}
        ),
        "expires_at": (
            _OMITTED_TIME if message.expires_at == "" else {"value": message.expires_at}
        ),
        "id": message.id,
        "metadata": message.metadata,
        "recipient_email": message.recipient_email,
        "sender_email": message.sender_email,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _encode_json(value: dict[str, object]) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _encode_bytes(rendered)


def _encode_bytes(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_bytes(value: str) -> bytes:
    if not value:
        raise ValueError("empty token segment")
    padding = "=" * (-len(value) % 4)
    return b64decode(value + padding, altchars=b"-_", validate=True)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("attestation clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _constant_time_text_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
