from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
from typing import Literal

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tailwag_memory.config import load_env_file

_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="TailwagBearer",
    description="Use the value configured in TAILWAG_API_BEARER_TOKEN.",
)


@dataclass(frozen=True)
class ApiPrincipal:
    """Authenticated Tailwag API caller."""

    kind: Literal["admin", "robot"]
    robot_id: str = ""


class RelayAuthConfigurationError(ValueError):
    """Relay authentication configuration is missing or ambiguous."""


def _configured_auth() -> tuple[str, dict[str, str]]:
    """Load and validate the configured admin and robot credentials once."""
    load_env_file()
    admin_token = str(os.getenv("TAILWAG_API_BEARER_TOKEN") or "").strip()
    raw = str(os.getenv("TAILWAG_ROBOT_API_TOKENS_JSON") or "").strip()
    if not raw:
        return admin_token, {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RelayAuthConfigurationError(
            "TAILWAG_ROBOT_API_TOKENS_JSON is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise RelayAuthConfigurationError(
            "TAILWAG_ROBOT_API_TOKENS_JSON must be an object"
        )
    tokens: dict[str, str] = {}
    for robot_id, token in payload.items():
        rendered_robot_id = str(robot_id or "").strip()
        rendered_token = str(token or "").strip()
        if not rendered_robot_id or not rendered_token:
            raise RelayAuthConfigurationError(
                "TAILWAG_ROBOT_API_TOKENS_JSON contains an invalid entry"
            )
        if rendered_token in tokens:
            raise RelayAuthConfigurationError(
                "TAILWAG_ROBOT_API_TOKENS_JSON contains duplicate tokens"
            )
        tokens[rendered_token] = rendered_robot_id
    if admin_token and admin_token in tokens:
        raise RelayAuthConfigurationError(
            "Tailwag API authentication scopes contain a duplicate token"
        )
    return admin_token, tokens


def validate_relay_auth_configuration() -> dict[str, str]:
    """Return configured robot tokens or raise a readiness-safe error."""
    _, robot_tokens = _configured_auth()
    if not robot_tokens:
        raise RelayAuthConfigurationError(
            "TAILWAG_ROBOT_API_TOKENS_JSON must configure at least one robot"
        )
    return robot_tokens


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> ApiPrincipal:
    """Require a configured bearer token for private API routes."""
    try:
        token, robot_tokens = _configured_auth()
        if not token and not robot_tokens:
            raise RelayAuthConfigurationError(
                "Tailwag API bearer authentication is not configured"
            )
    except RelayAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = credentials.credentials
    if token and hmac.compare_digest(presented, token):
        return ApiPrincipal(kind="admin")
    for robot_token, robot_id in robot_tokens.items():
        if hmac.compare_digest(presented, robot_token):
            return ApiPrincipal(kind="robot", robot_id=robot_id)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_robot_principal(
    principal: ApiPrincipal = Depends(require_bearer_token),
) -> ApiPrincipal:
    """Require a robot-bound credential for relay operations."""
    if principal.kind != "robot" or not principal.robot_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Robot-bound bearer token required",
        )
    return principal


def require_admin_principal(
    principal: ApiPrincipal = Depends(require_bearer_token),
) -> ApiPrincipal:
    """Keep robot-scoped credentials out of memory and biometric operations."""
    if principal.kind != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative bearer token required",
        )
    return principal
