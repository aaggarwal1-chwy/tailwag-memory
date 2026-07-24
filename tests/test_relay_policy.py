from __future__ import annotations

import unittest

from tailwag_memory.relay_policy import (
    OpenAIRelaySafetyProvider,
    RelaySafetyMalformedResponseError,
    RelaySafetyTimeoutError,
    RelaySafetyUnavailableError,
)


class _Responses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"output_text": self.output_text}


class _Client:
    def __init__(self, output_text: str) -> None:
        self.responses = _Responses(output_text)
        self.option_calls: list[dict[str, object]] = []

    def with_options(self, **kwargs: object) -> "_Client":
        self.option_calls.append(kwargs)
        return self


class _FailingResponses:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create(self, **kwargs: object) -> dict[str, str]:
        raise self.error


class _FailingClient:
    def __init__(self, error: Exception) -> None:
        self.responses = _FailingResponses(error)


class RelaySafetyProviderTest(unittest.TestCase):
    def test_returns_structured_allowed_decision(self) -> None:
        client = _Client('{"allowed":true,"reason":""}')
        provider = OpenAIRelaySafetyProvider(api_key=None, model="test-model", client=client)

        result = provider.screen(body="The 3 PM meeting moved to room 204.")

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "")
        self.assertEqual(client.responses.calls[0]["model"], "test-model")
        self.assertEqual(client.responses.calls[0]["timeout"], 8)
        self.assertEqual(
            client.option_calls,
            [{"timeout": 8, "max_retries": 1}],
        )

    def test_returns_structured_rejection_without_echoing_body(self) -> None:
        client = _Client('{"allowed":false,"reason":"Threatening content is not allowed."}')
        provider = OpenAIRelaySafetyProvider(api_key=None, model="test-model", client=client)

        result = provider.screen(body="unsafe example")

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "Threatening content is not allowed.")

    def test_invalid_provider_response_fails_closed(self) -> None:
        provider = OpenAIRelaySafetyProvider(
            api_key=None,
            model="test-model",
            client=_Client('{"allowed":"yes","reason":""}'),
        )

        with self.assertRaisesRegex(RelaySafetyMalformedResponseError, "invalid decision"):
            provider.screen(body="hello")

    def test_bounds_timeout_and_retries_for_gateway_budget(self) -> None:
        for timeout in (0, 11):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                    OpenAIRelaySafetyProvider(
                        api_key=None,
                        model="test-model",
                        timeout_seconds=timeout,
                    )
        for retries in (-1, 2):
            with self.subTest(retries=retries):
                with self.assertRaisesRegex(ValueError, "max_retries"):
                    OpenAIRelaySafetyProvider(
                        api_key=None,
                        model="test-model",
                        max_retries=retries,
                    )

    def test_classifies_upstream_timeout_and_unavailability(self) -> None:
        timeout_type = type("APITimeoutError", (Exception,), {})
        provider = OpenAIRelaySafetyProvider(
            api_key=None,
            model="test-model",
            client=_FailingClient(timeout_type("late")),
        )
        with self.assertRaises(RelaySafetyTimeoutError):
            provider.screen(body="hello")

        unavailable = OpenAIRelaySafetyProvider(
            api_key=None,
            model="test-model",
            client=_FailingClient(ConnectionError("offline")),
        )
        with self.assertRaises(RelaySafetyUnavailableError):
            unavailable.screen(body="hello")


if __name__ == "__main__":
    unittest.main()
