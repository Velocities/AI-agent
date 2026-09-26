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
    ACCESS_INCOMPLETE_CODE,
    ACCESS_INCOMPLETE_MESSAGE,
    ACCESS_PENDING_CODE,
    ACCESS_PENDING_MESSAGE,
    AccessStatus,
)
from ai_agent.deployment.identity import normalize_linux_username, suggest_linux_username


@dataclass(frozen=True)
class AccessRecord:
    user_id: str
    status: AccessStatus
    display_name: str
    email: str
    linux_username: str
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

    def authorize(
        self,
        user_id: str,
        *,
        email: str = "",
        display_name: str = "",
    ) -> None:
        """Allow approved users; create pending once; raise AccessGateError otherwise."""
        owner = _require_user_id(user_id)
        profile_email = email.strip()[:320]
        profile_name = display_name.strip()[:200]
        now = _utcnow()
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            if row is None:
                db.add(
                    DeploymentAccessRow(
                        user_id=owner,
                        status=AccessStatus.PENDING.value,
                        display_name=profile_name,
                        email=profile_email,
                        linux_username="",
                        created_at=now,
                        updated_at=now,
                        approved_at=None,
                    )
                )
                db.commit()
                raise AccessGateError(ACCESS_PENDING_CODE, ACCESS_PENDING_MESSAGE)
            _apply_profile(row, email=profile_email, display_name=profile_name, now=now)
            if row.status == AccessStatus.APPROVED.value:
                if not row.linux_username.strip():
                    db.commit()
                    raise AccessGateError(
                        ACCESS_INCOMPLETE_CODE,
                        ACCESS_INCOMPLETE_MESSAGE,
                    )
                db.commit()
                return
            if row.status == AccessStatus.DENIED.value:
                db.commit()
                raise AccessGateError(ACCESS_DENIED_CODE, ACCESS_DENIED_MESSAGE)
            db.commit()
            raise AccessGateError(ACCESS_PENDING_CODE, ACCESS_PENDING_MESSAGE)

    def approve(
        self,
        user_id: str,
        *,
        linux_username: str | None = None,
    ) -> AccessRecord:
        owner = _require_user_id(user_id)
        now = _utcnow()
        with self._session() as db:
            row = db.get(DeploymentAccessRow, owner)
            if row is None:
                row = DeploymentAccessRow(
                    user_id=owner,
                    status=AccessStatus.APPROVED.value,
                    display_name="",
                    email="",
                    linux_username="",
                    created_at=now,
                    updated_at=now,
                    approved_at=now,
                )
                db.add(row)
            else:
                row.status = AccessStatus.APPROVED.value
                row.updated_at = now
                row.approved_at = now
            resolved = _resolve_linux_username(row, linux_username)
            row.linux_username = resolved
            row.updated_at = now
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
                    email="",
                    linux_username="",
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


def _apply_profile(
    row: DeploymentAccessRow,
    *,
    email: str,
    display_name: str,
    now: datetime,
) -> None:
    changed = False
    if email and email != row.email:
        row.email = email
        changed = True
    if display_name and display_name != row.display_name:
        row.display_name = display_name
        changed = True
    if changed:
        row.updated_at = now


def _resolve_linux_username(
    row: DeploymentAccessRow,
    explicit: str | None,
) -> str:
    if explicit is not None and explicit.strip():
        return normalize_linux_username(explicit)
    if row.linux_username.strip():
        return normalize_linux_username(row.linux_username)
    suggested = suggest_linux_username(row.email)
    if suggested:
        return suggested
    raise ValueError(
        "Linux username is required (--run-as). Could not infer a safe name from email."
    )


def _to_record(row: DeploymentAccessRow) -> AccessRecord:
    return AccessRecord(
        user_id=row.user_id,
        status=AccessStatus(row.status),
        display_name=row.display_name or "",
        email=row.email or "",
        linux_username=row.linux_username or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
        approved_at=row.approved_at,
    )
