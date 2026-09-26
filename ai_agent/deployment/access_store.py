from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import DeploymentAccessRow
from ai_agent.deployment.access import (
    ACCESS_DENIED_CODE,
    ACCESS_DENIED_MESSAGE,
    ACCESS_PENDING_CODE,
    ACCESS_PENDING_MESSAGE,
    AccessStatus,
)


@dataclass(frozen=True)
class AccessRecord:
    user_id: str
    status: AccessStatus
    display_name: str
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class DeploymentAccessStore:
    def __init__(self, engine: Engine):
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def get(self, user_id: str) -> AccessRecord | None:
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            return _to_record(row) if row else None

    def authorize(self, user_id: str, *, display_name: str = "") -> None:
        """Allow approved users; create pending once; raise AccessGateError otherwise."""
        owner = _require_user_id(user_id)
        now = _utcnow()
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            if row is None:
                db.add(
                    DeploymentAccessRow(
                        user_id=owner,
                        status=AccessStatus.PENDING.value,
                        display_name=display_name.strip()[:200],
                        created_at=now,
                        updated_at=now,
                        approved_at=None,
                    )
                )
                db.commit()
                raise AccessGateError(ACCESS_PENDING_CODE, ACCESS_PENDING_MESSAGE)
            if row.status == AccessStatus.APPROVED.value:
                return
            if row.status == AccessStatus.DENIED.value:
                raise AccessGateError(ACCESS_DENIED_CODE, ACCESS_DENIED_MESSAGE)
            raise AccessGateError(ACCESS_PENDING_CODE, ACCESS_PENDING_MESSAGE)

    def approve(self, user_id: str) -> AccessRecord:
        owner = _require_user_id(user_id)
        now = _utcnow()
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            if row is None:
                row = DeploymentAccessRow(
                    user_id=owner,
                    status=AccessStatus.APPROVED.value,
                    display_name="",
                    created_at=now,
                    updated_at=now,
                    approved_at=now,
                )
                db.add(row)
            else:
                row.status = AccessStatus.APPROVED.value
                row.updated_at = now
                row.approved_at = now
            db.commit()
            db.refresh(row)
            return _to_record(row)

    def deny(self, user_id: str) -> AccessRecord:
        owner = _require_user_id(user_id)
        now = _utcnow()
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            if row is None:
                row = DeploymentAccessRow(
                    user_id=owner,
                    status=AccessStatus.DENIED.value,
                    display_name="",
                    created_at=now,
                    updated_at=now,
                    approved_at=None,
                )
                db.add(row)
            else:
                row.status = AccessStatus.DENIED.value
                row.updated_at = now
            db.commit()
            db.refresh(row)
            return _to_record(row)

    def list_by_status(self, status: AccessStatus | None = None) -> list[AccessRecord]:
        with self._session() as db:
            query = select(DeploymentAccessRow).order_by(DeploymentAccessRow.created_at)
            if status is not None:
                query = query.where(DeploymentAccessRow.status == status.value)
            rows = db.scalars(query).all()
            return [_to_record(row) for row in rows]

    def _session(self) -> Session:
        return self._session_factory()


class AccessGateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise ValueError("user_id is required.")
    return owner


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_record(row: DeploymentAccessRow) -> AccessRecord:
    return AccessRecord(
        user_id=row.user_id,
        status=AccessStatus(row.status),
        display_name=row.display_name or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
        approved_at=row.approved_at,
    )
