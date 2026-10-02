from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import ExecutionTargetRow
from ai_agent.execution_targets.store import (
    RESERVED_LOCAL_NAME,
    TargetConfigError,
    validate_target_name,
)


@dataclass(frozen=True)
class ExecutionTargetRecord:
    id: str
    user_id: str
    name: str
    type: Literal["ssh", "docker"]
    spec: dict[str, Any]


class UserExecutionTargetRepository:
    def __init__(self, engine: Engine):
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def list_for_user(self, user_id: str) -> list[ExecutionTargetRecord]:
        owner = _require_user_id(user_id)
        with self._session() as db:
            rows = db.scalars(
                select(ExecutionTargetRow)
                .where(ExecutionTargetRow.user_id == owner)
                .order_by(ExecutionTargetRow.name)
            ).all()
            return [_to_record(row) for row in rows]

    def get_by_name(self, user_id: str, name: str) -> ExecutionTargetRecord | None:
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = db.scalar(
                select(ExecutionTargetRow).where(
                    ExecutionTargetRow.user_id == owner,
                    ExecutionTargetRow.name == name,
                )
            )
            return _to_record(row) if row else None

    def get_ssh_by_name(self, user_id: str, name: str) -> ExecutionTargetRecord | None:
        rec = self.get_by_name(user_id, name)
        if rec is None or rec.type != "ssh":
            return None
        return rec

    def add_ssh(
        self,
        user_id: str,
        *,
        name: str,
        host: str,
        user: str,
        port: int,
        description: str = "",
        target_id: str | None = None,
    ) -> ExecutionTargetRecord:
        return self._add(
            user_id,
            name=name,
            type="ssh",
            spec={
                "host": host.strip(),
                "user": user.strip(),
                "port": int(port),
                "description": description.strip(),
            },
            target_id=target_id,
        )

    def add_docker(
        self,
        user_id: str,
        *,
        name: str,
        container: str,
        description: str = "",
        docker_bin: str = "docker",
        user: str = "",
        target_id: str | None = None,
    ) -> ExecutionTargetRecord:
        return self._add(
            user_id,
            name=name,
            type="docker",
            spec={
                "container": container.strip(),
                "description": description.strip(),
                "docker_bin": (docker_bin or "docker").strip(),
                "user": user.strip(),
            },
            target_id=target_id,
        )

    def _add(
        self,
        user_id: str,
        *,
        name: str,
        type: str,
        spec: dict[str, Any],
        target_id: str | None,
    ) -> ExecutionTargetRecord:
        owner = _require_user_id(user_id)
        validate_target_name(name)
        if name == RESERVED_LOCAL_NAME:
            raise TargetConfigError("'local' is reserved for this machine.")
        tid = target_id or str(uuid.uuid4())
        now = _utcnow()
        with self._session() as db:
            existing = db.scalar(
                select(ExecutionTargetRow).where(
                    ExecutionTargetRow.user_id == owner,
                    ExecutionTargetRow.name == name,
                )
            )
            if existing is not None:
                raise TargetConfigError(f"Target {name!r} already exists for this user.")
            row = ExecutionTargetRow(
                id=tid,
                user_id=owner,
                name=name,
                type=type,
                spec_json=spec,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _to_record(row)

    def _session(self) -> Session:
        return self._session_factory()


def _require_user_id(user_id: str) -> str:
    cleaned = user_id.strip()
    if not cleaned:
        raise ValueError("user_id is required")
    return cleaned


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_record(row: ExecutionTargetRow) -> ExecutionTargetRecord:
    kind = row.type
    if kind not in ("ssh", "docker"):
        raise TargetConfigError(f"Unsupported target type {kind!r}")
    return ExecutionTargetRecord(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        type=kind,
        spec=dict(row.spec_json or {}),
    )
