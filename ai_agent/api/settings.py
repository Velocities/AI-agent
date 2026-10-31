"""Per-user preferences.

`strip_image_metadata` defaults to true. Setting it false persists GPS,
camera, timestamp, and other image tags on disk under ATTACHMENT_ROOT and
sends those bytes to the model. It is not a split that stores the original
and strips only the provider payload.

Personalization fields are optional on PATCH. Omitted fields stay as stored.
A name requires its sounds-like respelling. That respelling is for speech
only and is not repeated in the model prompt. Transcription, wake and closing
phrases, and voice command approval are speech settings too: stored per user
on this server, and never copied into the model prompt.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.conversations.personalization import (
    DEFAULT_STT_PROVIDER,
    PersonalizationError,
    UserPreferences,
    selectable_timezones,
)
from ai_agent.conversations.user_settings import UserSettingsStore

router = APIRouter(tags=["settings"])


class UserSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strip_image_metadata: bool = True
    agent_name: str = ""
    agent_name_pronunciation: str = ""
    user_name: str = ""
    user_name_pronunciation: str = ""
    coding_preferences: str = ""
    reply_length: str = "normal"
    timezone: str = ""
    stt_provider: str = DEFAULT_STT_PROVIDER
    wake_phrase: str = ""
    close_phrase: str = ""
    voice_command_approval: bool = False

    @classmethod
    def from_preferences(cls, prefs: UserPreferences) -> UserSettingsBody:
        return cls(
            strip_image_metadata=prefs.strip_image_metadata,
            agent_name=prefs.agent_name,
            agent_name_pronunciation=prefs.agent_name_pronunciation,
            user_name=prefs.user_name,
            user_name_pronunciation=prefs.user_name_pronunciation,
            coding_preferences=prefs.coding_preferences,
            reply_length=prefs.reply_length,
            timezone=prefs.timezone,
            stt_provider=prefs.stt_provider,
            wake_phrase=prefs.wake_phrase,
            close_phrase=prefs.close_phrase,
            voice_command_approval=prefs.voice_command_approval,
        )


class TimezoneCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezones: list[str]


class UserSettingsPatch(BaseModel):
    """Partial update. Fields left out are not changed."""

    model_config = ConfigDict(extra="forbid")

    strip_image_metadata: bool | None = None
    agent_name: str | None = None
    agent_name_pronunciation: str | None = None
    user_name: str | None = None
    user_name_pronunciation: str | None = None
    coding_preferences: str | None = None
    reply_length: str | None = None
    timezone: str | None = None
    stt_provider: str | None = None
    wake_phrase: str | None = None
    close_phrase: str | None = None
    voice_command_approval: bool | None = None


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
    return UserSettingsBody.from_preferences(settings.get_preferences(user.user_id))


@router.get("/api/timezones", response_model=TimezoneCatalog)
def list_timezones(
    _user: AuthenticatedUser = Depends(require_deployment_access),
) -> TimezoneCatalog:
    """IANA zones the client may offer. Each one passes settings validation."""
    return TimezoneCatalog(timezones=list(selectable_timezones()))


@router.patch("/api/me/settings", response_model=UserSettingsBody)
def update_settings(
    body: UserSettingsPatch,
    user: AuthenticatedUser = Depends(require_deployment_access),
    settings: UserSettingsStore = Depends(get_user_settings),
) -> UserSettingsBody:
    current = settings.get_preferences(user.user_id)
    merged = _merge(current, body)
    try:
        stored = settings.save_preferences(user.user_id, merged)
    except PersonalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return UserSettingsBody.from_preferences(stored)


def _merge(current: UserPreferences, body: UserSettingsPatch) -> UserPreferences:
    provided = body.model_fields_set

    def text(field: str, current_value: str) -> str:
        if field not in provided:
            return current_value
        value = getattr(body, field)
        return "" if value is None else value

    strip = current.strip_image_metadata
    if "strip_image_metadata" in provided and body.strip_image_metadata is not None:
        strip = body.strip_image_metadata
    voice = current.voice_command_approval
    if "voice_command_approval" in provided and body.voice_command_approval is not None:
        voice = body.voice_command_approval
    return UserPreferences(
        strip_image_metadata=strip,
        agent_name=text("agent_name", current.agent_name),
        agent_name_pronunciation=text("agent_name_pronunciation", current.agent_name_pronunciation),
        user_name=text("user_name", current.user_name),
        user_name_pronunciation=text("user_name_pronunciation", current.user_name_pronunciation),
        coding_preferences=text("coding_preferences", current.coding_preferences),
        reply_length=text("reply_length", current.reply_length) or current.reply_length,
        timezone=text("timezone", current.timezone),
        stt_provider=text("stt_provider", current.stt_provider) or current.stt_provider,
        wake_phrase=text("wake_phrase", current.wake_phrase),
        close_phrase=text("close_phrase", current.close_phrase),
        voice_command_approval=voice,
    )
