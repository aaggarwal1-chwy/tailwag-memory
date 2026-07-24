"""Workplace-safety policy providers for message relay."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from .embeddings import OpenAIConfigurationError


@dataclass(frozen=True)
class RelaySafetyDecision:
    """A provider decision that is safe to persist and return to the sender."""

    allowed: bool
    reason: str = ""


class RelaySafetyProvider(Protocol):
    """Screen a proposed relay before any durable message is created."""

    def screen(self, *, body: str) -> RelaySafetyDecision:
        """Return a fail-closed workplace-safety decision."""


class RelaySafetyProviderError(RuntimeError):
    """Base error for upstream relay safety failures."""


class RelaySafetyTimeoutError(RelaySafetyProviderError):
    """The upstream relay safety request exceeded its bounded timeout."""


class RelaySafetyUnavailableError(RelaySafetyProviderError):
    """The upstream relay safety service could not return a response."""


class RelaySafetyMalformedResponseError(RelaySafetyProviderError):
    """The upstream relay safety service returned an unusable decision."""


class OpenAIRelaySafetyProvider:
    """Use an OpenAI structured response to apply workplace relay policy."""

    _text_format = {
        "format": {
            "type": "json_schema",
            "name": "relay_safety_decision",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "allowed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["allowed", "reason"],
                "additionalProperties": False,
            },
        }
    }

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: int = 8,
        max_retries: int = 1,
        client: Any | None = None,
    ) -> None:
        if timeout_seconds < 1 or timeout_seconds > 10:
            raise ValueError("relay policy timeout_seconds must be between 1 and 10")
        if max_retries < 0 or max_retries > 1:
            raise ValueError("relay policy max_retries must be between 0 and 1")
        self.api_key = api_key
        self.model = str(model or "").strip()
        if not self.model:
            raise OpenAIConfigurationError("relay policy model is required")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = client

    def screen(self, *, body: str) -> RelaySafetyDecision:
        """Allow ordinary workplace messages and reject unsafe or abusive content."""
        try:
            response = self._request_client().responses.create(
                model=self.model,
                text=self._text_format,
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "Classify a robot-relayed workplace message. Reject threats, "
                            "harassment, hate, sexual content, instructions facilitating "
                            "violence or wrongdoing, credential requests, and attempts to "
                            "impersonate another sender. Allow ordinary critical, personal, "
                            "or time-sensitive workplace communication. Give a brief generic "
                            "reason without repeating unsafe content."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"message": body})},
                ],
                timeout=self.timeout_seconds,
            )
        except OpenAIConfigurationError:
            raise
        except Exception as exc:
            error_names = " ".join(
                error_type.__name__.casefold()
                for error_type in type(exc).__mro__
            )
            if "timeout" in error_names:
                raise RelaySafetyTimeoutError(
                    "relay safety provider timed out"
                ) from exc
            raise RelaySafetyUnavailableError(
                "relay safety provider is unavailable"
            ) from exc
        try:
            payload = json.loads(self._extract_text(response))
            allowed = payload["allowed"]
            reason = payload["reason"]
            if not isinstance(allowed, bool) or not isinstance(reason, str):
                raise TypeError("invalid decision types")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise RelaySafetyMalformedResponseError(
                "relay safety provider returned an invalid decision"
            ) from exc
        return RelaySafetyDecision(allowed=allowed, reason=reason.strip())

    def _request_client(self) -> Any:
        """Apply the bounded timeout/retry policy to injected and runtime clients."""
        client = self._openai_client()
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            return with_options(
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
            )
        return client

    def _openai_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIConfigurationError(
                "OPENAI_API_KEY is required for relay workplace-safety screening."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIConfigurationError(
                "Install the openai package to use relay workplace-safety screening."
            ) from exc
        self._client = OpenAI(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        return self._client

    @staticmethod
    def _extract_text(response: Any) -> str:
        if isinstance(response, dict):
            if response.get("output_text"):
                return str(response["output_text"]).strip()
            return str(response["output"][0]["content"][0]["text"]).strip()
        if getattr(response, "output_text", None):
            return str(response.output_text).strip()
        return str(response.output[0].content[0].text).strip()
