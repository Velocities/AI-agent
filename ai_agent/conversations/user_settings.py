"""Per-user preferences stored beside conversations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import UserSettingRow


class UserSettingsStore:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_strip_image_metadata(self, user_id: str) -> bool:
        """True when no row exists. Stripping is the default."""
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.get(UserSettingRow, owner)
            if row is None:
                return True
            return bool(row.strip_image_metadata)

    def set_strip_image_metadata(self, user_id: str, value: bool) -> bool:
        """Upsert. Return the stored value."""
        owner = _require_user_id(user_id)
        now = datetime.now(timezone.utc)
        stored = 1 if value else 0
        with self._session() as db:
            row = db.get(UserSettingRow, owner)
            if row is None:
                row = UserSettingRow(
                    user_id=owner,
                    strip_image_metadata=stored,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.strip_image_metadata = stored
                row.updated_at = now
            db.commit()
            return bool(row.strip_image_metadata)

    def _session(self) -> Session:
        return self._sessions()


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise ValueError("user_id is required.")
    return owner
