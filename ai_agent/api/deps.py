from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_agent.api.auth import (
    AuthenticatedUser,
    AuthUnavailableError,
    InvalidTokenError,
)
from ai_agent.deployment.access_store import AccessGateError, DeploymentAccessStore

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


def require_deployment_access(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """JWT valid and this deployment's whitelist allows the user."""
    store: DeploymentAccessStore | None = getattr(request.app.state, "access_store", None)
    if store is None:
        return user
    try:
        store.authorize(user.user_id)
    except AccessGateError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    return user
