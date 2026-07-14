from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tailwag_memory.config import load_env_file

_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="TailwagBearer",
    description="Use the value configured in TAILWAG_API_BEARER_TOKEN.",
)


def _configured_token() -> str:
    """Return the configured API bearer token."""
    load_env_file()
    return str(os.getenv("TAILWAG_API_BEARER_TOKEN") or "").strip()


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Require a configured bearer token for private API routes."""
    token = _configured_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TAILWAG_API_BEARER_TOKEN is not configured",
        )

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(credentials.credentials, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
