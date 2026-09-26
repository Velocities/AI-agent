from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_agent.api.auth import (
    AuthenticatedUser,
    AuthUnavailableError,
    InvalidTokenError,
    TokenVerifier,
)

_bearer = HTTPBearer(auto_error=False)
_AUTH_HEADER = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """Require a Supabase access token. Mount this on every agent route."""
    verifier: TokenVerifier | None = request.app.state.verifier
    if verifier is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured.",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token.",
            headers=_AUTH_HEADER,
        )
    try:
        return verifier.verify(credentials.credentials.strip())
    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
            headers=_AUTH_HEADER,
        ) from None
    except AuthUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Could not verify tokens right now.",
        ) from None
