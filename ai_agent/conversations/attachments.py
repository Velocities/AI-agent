"""SQLite catalog for attachment bytes stored outside the database."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.attachments.types import Attachment
from ai_agent.conversations.models import AttachmentRow


class AttachmentCatalog:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def insert(self, db: Session, attachment: Attachment) -> None:
        db.add(
            AttachmentRow(
                id=attachment.id,
                user_id=attachment.user_id,
                conversation_id=attachment.conversation_id,
                kind=attachment.kind,
                media_type=attachment.media_type,
                byte_size=attachment.byte_size,
                checksum=attachment.checksum,
                created_at=datetime.now(timezone.utc),
            )
        )

    def get(self, user_id: str, attachment_id: str) -> Attachment | None:
        with self._session() as db:
            row = db.scalar(
                select(AttachmentRow).where(
                    AttachmentRow.id == attachment_id,
                    AttachmentRow.user_id == user_id,
                )
            )
            return None if row is None else _attachment(row)

    def owner_of(self, attachment_id: str) -> str | None:
        """User id that owns this catalog row, if any. Does not return bytes."""
        with self._session() as db:
            return db.scalar(
                select(AttachmentRow.user_id).where(AttachmentRow.id == attachment_id)
            )

    def list_for_user(self, user_id: str) -> list[Attachment]:
        with self._session() as db:
            rows = db.scalars(
                select(AttachmentRow)
                .where(AttachmentRow.user_id == user_id)
                .order_by(AttachmentRow.created_at.asc(), AttachmentRow.id.asc())
            ).all()
            return [_attachment(row) for row in rows]

    def totals_for_user(self, user_id: str) -> tuple[int, int]:
        with self._session() as db:
            total_bytes = db.scalar(
                select(func.coalesce(func.sum(AttachmentRow.byte_size), 0)).where(
                    AttachmentRow.user_id == user_id
                )
            )
            count = db.scalar(
                select(func.count()).select_from(AttachmentRow).where(
                    AttachmentRow.user_id == user_id
                )
            )
            return int(total_bytes or 0), int(count or 0)

    def delete_for_conversation(
        self,
        db: Session,
        user_id: str,
        conversation_id: str,
    ) -> list[str]:
        rows = db.scalars(
            select(AttachmentRow).where(
                AttachmentRow.user_id == user_id,
                AttachmentRow.conversation_id == conversation_id,
            )
        ).all()
        ids = [row.id for row in rows]
        for row in rows:
            db.delete(row)
        return ids

    def delete_ids(self, db: Session, user_id: str, ids: list[str]) -> None:
        if not ids:
            return
        rows = db.scalars(
            select(AttachmentRow).where(
                AttachmentRow.user_id == user_id,
                AttachmentRow.id.in_(ids),
            )
        ).all()
        for row in rows:
            db.delete(row)

    def all_ids(self) -> set[str]:
        with self._session() as db:
            return set(db.scalars(select(AttachmentRow.id)).all())

    def _session(self) -> Session:
        return self._sessions()


def _attachment(row: AttachmentRow) -> Attachment:
    return Attachment(
        id=row.id,
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        kind=row.kind,
        media_type=row.media_type,
        byte_size=row.byte_size,
        checksum=row.checksum,
    )
