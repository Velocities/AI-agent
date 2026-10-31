"""Per-user preferences stored beside conversations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import UserSettingRow
from ai_agent.conversations.personalization import (
    DEFAULT_STT_PROVIDER,
    STT_PROVIDERS,
    UserPreferences,
    normalize_preferences,
)


class UserSettingsStore:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_strip_image_metadata(self, user_id: str) -> bool:
        """True when no row exists. Stripping is the default."""
        return self.get_preferences(user_id).strip_image_metadata

    def set_strip_image_metadata(self, user_id: str, value: bool) -> bool:
        """Upsert the image flag without changing personalization."""
        current = self.get_preferences(user_id)
        # replace() changes the image flag and leaves speech settings alone.
        stored = self.save_preferences(user_id, replace(current, strip_image_metadata=value))
        return stored.strip_image_metadata

    def get_preferences(self, user_id: str) -> UserPreferences:
        """Defaults when the user has no row. Null columns use those defaults."""
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.get(UserSettingRow, owner)
            if row is None:
                return UserPreferences()
            length = row.reply_length if row.reply_length in {"brief", "normal", "thorough"} else "normal"
            stt = row.stt_provider if row.stt_provider in STT_PROVIDERS else DEFAULT_STT_PROVIDER
            return UserPreferences(
                strip_image_metadata=bool(row.strip_image_metadata),
                agent_name=row.agent_name or "",
                agent_name_pronunciation=row.agent_name_pronunciation or "",
                user_name=row.user_name or "",
                user_name_pronunciation=row.user_name_pronunciation or "",
                coding_preferences=row.coding_preferences or "",
                reply_length=length,
                timezone=row.timezone or "",
                stt_provider=stt,
                wake_phrase=row.wake_phrase or "",
                close_phrase=row.close_phrase or "",
                voice_command_approval=bool(row.voice_command_approval),
            )

    def save_preferences(self, user_id: str, prefs: UserPreferences) -> UserPreferences:
        """Validate and upsert the full preference row. Return the stored value."""
        owner = _require_user_id(user_id)
        stored = normalize_preferences(prefs)
        now = datetime.now(timezone.utc)
        with self._session() as db:
            row = db.get(UserSettingRow, owner)
            if row is None:
                row = UserSettingRow(user_id=owner, updated_at=now)
                db.add(row)
            _write_row(row, stored, now)
            db.commit()
            return stored

    def _session(self) -> Session:
        return self._sessions()


def _write_row(row: UserSettingRow, prefs: UserPreferences, now: datetime) -> None:
    row.strip_image_metadata = 1 if prefs.strip_image_metadata else 0
    row.agent_name = prefs.agent_name or None
    row.agent_name_pronunciation = prefs.agent_name_pronunciation or None
    row.user_name = prefs.user_name or None
    row.user_name_pronunciation = prefs.user_name_pronunciation or None
    row.coding_preferences = prefs.coding_preferences or None
    row.reply_length = None if prefs.reply_length == "normal" else prefs.reply_length
    row.timezone = prefs.timezone or None
    # Null keeps the "unset means default" shape the other personalization columns use.
    row.stt_provider = None if prefs.stt_provider == DEFAULT_STT_PROVIDER else prefs.stt_provider
    row.wake_phrase = prefs.wake_phrase or None
    row.close_phrase = prefs.close_phrase or None
    row.voice_command_approval = 1 if prefs.voice_command_approval else None
    row.updated_at = now


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise ValueError("user_id is required.")
    return owner
