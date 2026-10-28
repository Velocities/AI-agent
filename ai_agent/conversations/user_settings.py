"""Per-user preferences stored beside conversations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import UserSettingRow
from ai_agent.conversations.personalization import UserPreferences, normalize_preferences


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
        stored = self.save_preferences(
            user_id,
            UserPreferences(
                strip_image_metadata=value,
                agent_name=current.agent_name,
                agent_name_pronunciation=current.agent_name_pronunciation,
                user_name=current.user_name,
                user_name_pronunciation=current.user_name_pronunciation,
                coding_preferences=current.coding_preferences,
                reply_length=current.reply_length,
                timezone=current.timezone,
            ),
        )
        return stored.strip_image_metadata

    def get_preferences(self, user_id: str) -> UserPreferences:
        """Defaults when the user has no row. Null columns use those defaults."""
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.get(UserSettingRow, owner)
            if row is None:
                return UserPreferences()
            length = row.reply_length if row.reply_length in {"brief", "normal", "thorough"} else "normal"
            return UserPreferences(
                strip_image_metadata=bool(row.strip_image_metadata),
                agent_name=row.agent_name or "",
                agent_name_pronunciation=row.agent_name_pronunciation or "",
                user_name=row.user_name or "",
                user_name_pronunciation=row.user_name_pronunciation or "",
                coding_preferences=row.coding_preferences or "",
                reply_length=length,
                timezone=row.timezone or "",
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
    row.updated_at = now


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise ValueError("user_id is required.")
    return owner
