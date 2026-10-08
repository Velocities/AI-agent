"""SQLite allowlist of Supabase users who may read host monitoring.

This is the current source of truth for monitoring admins. It is not
deployment_access: approving a user to run the agent does not insert a row
here, and granting monitoring does not approve agent access.

Add and remove people with ``ai-agent config monitoring grant|revoke``.
The API reads this table on each request. Operator-facing behavior is also
described in the README section "Monitoring admins" and in
deploy/systemd/README.md. Change those notes together with this module
before treating the rules as final.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import MonitoringAdminRow


@dataclass(frozen=True)
class MonitoringAdminRecord:
    user_id: str
    created_at: datetime


class MonitoringAdminStore:
    def __init__(self, engine: Engine):
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def contains(self, user_id: str) -> bool:
        owner = _require_user_id(user_id)
        with self._session() as db:
            return db.get(MonitoringAdminRow, owner) is not None

    def grant(self, user_id: str) -> tuple[MonitoringAdminRecord, bool]:
        """Insert the user. The bool is True when this call created the row."""
        owner = _require_user_id(user_id)
        now = datetime.now(timezone.utc)
        with self._session() as db:
            row = db.get(MonitoringAdminRow, owner)
            created = row is None
            if row is None:
                row = MonitoringAdminRow(user_id=owner, created_at=now)
                db.add(row)
                db.commit()
                db.refresh(row)
            return _to_record(row), created

    def revoke(self, user_id: str) -> bool:
        """Delete the row. False when that user id was not an admin."""
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.get(MonitoringAdminRow, owner)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def list_admins(self) -> list[MonitoringAdminRecord]:
        with self._session() as db:
            rows = db.scalars(
                select(MonitoringAdminRow).order_by(MonitoringAdminRow.created_at)
            ).all()
            return [_to_record(row) for row in rows]

    def _session(self) -> Session:
        return self._session_factory()


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise ValueError("user_id is required.")
    return owner


def _to_record(row: MonitoringAdminRow) -> MonitoringAdminRecord:
    return MonitoringAdminRecord(user_id=row.user_id, created_at=row.created_at)
