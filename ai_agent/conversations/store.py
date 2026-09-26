from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_agent.conversations.models import ConversationRow, MessageRow

MESSAGE_ROLES = frozenset({"user", "assistant", "tool"})
_TITLE_LIMIT = 80


class ConversationNotFound(LookupError):
    """No conversation with this id belongs to this user."""


class InvalidMessage(ValueError):
    """Role or payload the store will not keep."""


@dataclass(frozen=True)
class Conversation:
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    metadata: dict
    position: int


class ConversationStore:
    """Transcript storage for one process.

    Every method takes `user_id` from the verified token. Rows are never
    selected by conversation id alone. A later database is another class
    with these methods; callers should not open SQLAlchemy sessions.
    """

    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_conversation(self, user_id: str, *, title: str = "") -> Conversation:
        owner = _require_user_id(user_id)
        now = _now()
        row = ConversationRow(
            id=str(uuid4()),
            user_id=owner,
            title=_clean_title(title),
            created_at=now,
            updated_at=now,
        )
        with self._session() as db:
            db.add(row)
            db.commit()
            return _conversation(row)

    def list_conversations(self, user_id: str) -> list[Conversation]:
        owner = _require_user_id(user_id)
        with self._session() as db:
            rows = db.scalars(
                select(ConversationRow)
                .where(ConversationRow.user_id == owner)
                .order_by(ConversationRow.updated_at.desc(), ConversationRow.id.desc())
            ).all()
            return [_conversation(row) for row in rows]

    def get_conversation(self, user_id: str, conversation_id: str) -> Conversation | None:
        owner = _require_user_id(user_id)
        with self._session() as db:
            row = _owned(db, owner, conversation_id)
            return None if row is None else _conversation(row)

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        owner = _require_user_id(user_id)
        if role not in MESSAGE_ROLES:
            raise InvalidMessage(f"Unsupported message role {role!r}.")
        payload = dict(metadata or {})
        now = _now()
        with self._session() as db:
            conversation = _owned(db, owner, conversation_id)
            if conversation is None:
                raise ConversationNotFound(conversation_id)
            last = db.scalar(
                select(MessageRow.position)
                .where(MessageRow.conversation_id == conversation.id)
                .order_by(MessageRow.position.desc())
                .limit(1)
            )
            position = 0 if last is None else last + 1
            if not conversation.title and role == "user" and content.strip():
                conversation.title = _clean_title(content.strip().splitlines()[0])
            conversation.updated_at = now
            row = MessageRow(
                id=str(uuid4()),
                conversation_id=conversation.id,
                position=position,
                role=role,
                content=content,
                created_at=now,
                metadata_json=payload,
            )
            db.add(row)
            db.commit()
            return _message(row)

    def list_messages(self, user_id: str, conversation_id: str) -> list[Message]:
        owner = _require_user_id(user_id)
        with self._session() as db:
            conversation = _owned(db, owner, conversation_id)
            if conversation is None:
                raise ConversationNotFound(conversation_id)
            rows = db.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation.id)
                .order_by(MessageRow.position.asc())
            ).all()
            return [_message(row) for row in rows]

    def _session(self) -> Session:
        return self._sessions()


def _owned(db: Session, user_id: str, conversation_id: str) -> ConversationRow | None:
    return db.scalar(
        select(ConversationRow).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
    )


def _require_user_id(user_id: str) -> str:
    owner = user_id.strip()
    if not owner:
        raise InvalidMessage("user_id is required.")
    return owner


def _clean_title(title: str) -> str:
    return title.strip()[:_TITLE_LIMIT]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _conversation(row: ConversationRow) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _message(row: MessageRow) -> Message:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        created_at=_as_utc(row.created_at),
        metadata=dict(metadata),
        position=row.position,
    )
