from __future__ import annotations

import os
import secrets
from uuid import UUID

from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError, TokenVerifier
from ai_agent.config import Settings
from ai_agent.deployment.access import AccessStatus
from ai_agent.deployment.access_store import DeploymentAccessStore

# Stable default for single-user loopback chat (local client mode).
DEFAULT_LOCAL_STANDALONE_USER_ID = "00000000-0000-4000-8000-000000000001"


class LocalStandaloneVerifier:
    """Accept one shared bearer token and map it to a fixed Supabase-shaped user id."""

    def __init__(self, *, user_id: str, token: str, display_name: str = "local"):
        owner = str(UUID(user_id))
        secret = token.strip()
        if not secret:
            raise ValueError("LOCAL_STANDALONE_TOKEN must not be empty.")
        self._user_id = owner
        self._token = secret
        self._display_name = display_name.strip() or "local"

    def verify(self, token: str) -> AuthenticatedUser:
        if not token or not token.strip():
            raise InvalidTokenError("Missing bearer token.")
        if not secrets.compare_digest(token.strip(), self._token):
            raise InvalidTokenError("Invalid or expired token.")
        return AuthenticatedUser(
            user_id=self._user_id,
            email="",
            display_name=self._display_name,
        )


def local_standalone_enabled(settings: Settings) -> bool:
    if settings.local_standalone_mode:
        return True
    raw = os.environ.get("LOCAL_STANDALONE_MODE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_verifier(settings: Settings) -> tuple[TokenVerifier | None, Settings]:
    """Pick Supabase JWT verification or loopback shared-token auth."""
    if local_standalone_enabled(settings):
        token = (settings.local_standalone_token or "").strip() or os.environ.get(
            "LOCAL_STANDALONE_TOKEN", ""
        ).strip()
        if not token:
            token = secrets.token_urlsafe(32)
        user_id = (
            settings.local_standalone_user_id.strip()
            or os.environ.get("LOCAL_STANDALONE_USER_ID", "").strip()
            or DEFAULT_LOCAL_STANDALONE_USER_ID
        )
        updated = settings.model_copy(update={"local_standalone_token": token})
        verifier = LocalStandaloneVerifier(user_id=user_id, token=token)
        return verifier, updated
    return _build_supabase_verifier(settings), settings


def _build_supabase_verifier(settings: Settings) -> TokenVerifier | None:
    from ai_agent.api.auth import build_verifier

    return build_verifier(settings)


def bootstrap_local_standalone_access(
    store: DeploymentAccessStore,
    settings: Settings,
) -> None:
    """Ensure the fixed local user is approved so API routes behave like production."""
    if not local_standalone_enabled(settings):
        return
    user_id = (
        settings.local_standalone_user_id.strip()
        or os.environ.get("LOCAL_STANDALONE_USER_ID", "").strip()
        or DEFAULT_LOCAL_STANDALONE_USER_ID
    )
    linux_user = (
        settings.local_standalone_linux_user.strip()
        or os.environ.get("LOCAL_STANDALONE_LINUX_USER", "").strip()
        or os.environ.get("USER", "").strip()
        or os.environ.get("USERNAME", "").strip()
        or os.environ.get("LOGNAME", "").strip()
        or "local"
    )
    record = store.get(user_id)
    if (
        record is not None
        and record.status == AccessStatus.APPROVED
        and record.linux_username.strip()
    ):
        return
    try:
        store.approve(user_id, linux_username=linux_user)
    except ValueError:
        store.approve(user_id, linux_username="local")