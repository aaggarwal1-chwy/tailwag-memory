from __future__ import annotations

import json
import unittest
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from tailwag_memory.api.auth import (
        require_admin_principal,
        require_bearer_token,
        require_robot_principal,
        validate_relay_auth_configuration,
    )
except ModuleNotFoundError:  # pragma: no cover - optional API dependency guard
    HTTPException = None
    HTTPAuthorizationCredentials = None
    require_admin_principal = None
    require_bearer_token = None
    require_robot_principal = None
    validate_relay_auth_configuration = None


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    assert HTTPAuthorizationCredentials is not None
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@unittest.skipIf(HTTPException is None, "Install tailwag-memory[api] to run API auth tests.")
class RelayAuthenticationTest(unittest.TestCase):
    def test_robot_token_resolves_stable_robot_principal(self) -> None:
        tokens = json.dumps({"robot-bos3-01": "robot-secret"})
        with patch.dict(
            "os.environ",
            {
                "TAILWAG_API_BEARER_TOKEN": "admin-secret",
                "TAILWAG_ROBOT_API_TOKENS_JSON": tokens,
            },
            clear=True,
        ):
            principal = require_bearer_token(_credentials("robot-secret"))

        self.assertEqual(principal.kind, "robot")
        self.assertEqual(principal.robot_id, "robot-bos3-01")
        self.assertEqual(require_robot_principal(principal).robot_id, "robot-bos3-01")

    def test_admin_token_cannot_call_robot_bound_relay_route(self) -> None:
        with patch.dict(
            "os.environ",
            {"TAILWAG_API_BEARER_TOKEN": "admin-secret"},
            clear=True,
        ):
            principal = require_bearer_token(_credentials("admin-secret"))

        with self.assertRaises(HTTPException) as raised:
            require_robot_principal(principal)

        self.assertEqual(raised.exception.status_code, 403)

    def test_robot_token_cannot_call_admin_memory_routes(self) -> None:
        tokens = json.dumps({"robot-bos3-01": "robot-secret"})
        with patch.dict(
            "os.environ",
            {
                "TAILWAG_API_BEARER_TOKEN": "admin-secret",
                "TAILWAG_ROBOT_API_TOKENS_JSON": tokens,
            },
            clear=True,
        ):
            principal = require_bearer_token(_credentials("robot-secret"))

        with self.assertRaises(HTTPException) as raised:
            require_admin_principal(principal)

        self.assertEqual(raised.exception.status_code, 403)

    def test_duplicate_robot_tokens_fail_closed(self) -> None:
        tokens = json.dumps({"robot-1": "same-secret", "robot-2": "same-secret"})
        with patch.dict(
            "os.environ",
            {"TAILWAG_ROBOT_API_TOKENS_JSON": tokens},
            clear=True,
        ):
            with self.assertRaises(HTTPException) as raised:
                require_bearer_token(_credentials("same-secret"))

        self.assertEqual(raised.exception.status_code, 503)

    def test_admin_and_robot_token_collision_fails_closed(self) -> None:
        tokens = json.dumps({"robot-1": "shared-secret"})
        with patch.dict(
            "os.environ",
            {
                "TAILWAG_API_BEARER_TOKEN": "shared-secret",
                "TAILWAG_ROBOT_API_TOKENS_JSON": tokens,
            },
            clear=True,
        ):
            with self.assertRaises(HTTPException) as raised:
                require_bearer_token(_credentials("shared-secret"))

        self.assertEqual(raised.exception.status_code, 503)

    def test_unconfigured_auth_fails_closed(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                require_bearer_token(_credentials("anything"))

        self.assertEqual(raised.exception.status_code, 503)

    def test_relay_preflight_requires_at_least_one_robot_credential(self) -> None:
        with patch.dict(
            "os.environ",
            {"TAILWAG_API_BEARER_TOKEN": "admin-secret"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "at least one robot"):
                validate_relay_auth_configuration()


if __name__ == "__main__":
    unittest.main()
