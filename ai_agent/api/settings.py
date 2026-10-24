"""Per-user preferences.

`strip_image_metadata` defaults to true. Setting it false persists GPS,
camera, timestamp, and other image tags on disk under ATTACHMENT_ROOT and
sends those bytes to the model. It is not a split that stores the original
and strips only the provider payload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.conversations.user_settings import UserSettingsStore

router = APIRouter(tags=["settings"])


class UserSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strip_image_metadata: bool


def get_user_settings(request: Request) -> UserSettingsStore:
    store = getattr(request.app.state, "user_settings", None)
    if store is None:
        raise HTTPException(status_code=503, detail="User settings are not available.")
    return store


@router.get("/api/me/settings", response_model=UserSettingsBody)
def read_settings(
    user: AuthenticatedUser = Depends(require_deployment_access),
    settings: UserSettingsStore = Depends(get_user_settings),
) -> UserSettingsBody:
    """Return this user's preferences.

    strip_image_metadata defaults to true when the user has no row. Setting it
    false persists GPS, camera, timestamp, and other image tags on disk and
    sends them to the model.
    """
    return UserSettingsBody(
        strip_image_metadata=settings.get_strip_image_metadata(user.user_id)
    )


@router.patch("/api/me/settings", response_model=UserSettingsBody)
def update_settings(
    body: UserSettingsBody,
    user: AuthenticatedUser = Depends(require_deployment_access),
    settings: UserSettingsStore = Depends(get_user_settings),
) -> UserSettingsBody:
    stored = settings.set_strip_image_metadata(user.user_id, body.strip_image_metadata)
    return UserSettingsBody(strip_image_metadata=stored)
