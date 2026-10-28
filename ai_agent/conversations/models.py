from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[MessageRow]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class MessageRow(Base):
    """One transcript row.

    `metadata` is a JSON object so later tool calls, attachments, and
    execution records can hang off a message before they earn their own tables.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "position", name="uq_messages_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class DeploymentAccessRow(Base):
    """Who may use this deployment's API (local SQLite only, not Supabase)."""

    __tablename__ = "deployment_access"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    linux_username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonitoringAdminRow(Base):
    """Supabase users allowed to read host monitoring on this deployment.

    Separate from deployment_access: agent approval does not grant monitoring,
    and a monitoring admin is not approved to run agent commands. Grant and
    revoke behavior lives in ai_agent/deployment/monitoring_admin_store.py and
    ai_agent/cli/monitoring_cmd.py. Revise those with the README section
    "Monitoring admins" before treating the rules as final.
    """

    __tablename__ = "monitoring_admin"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserSettingRow(Base):
    """Per-user preferences. Missing row means the defaults (strip images on).

    Personalization columns are null until set. Null matches the empty-string
    and `normal` reply-length defaults.
    """

    __tablename__ = "user_setting"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strip_image_metadata: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent_name_pronunciation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_name_pronunciation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    coding_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_length: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttachmentRow(Base):
    """Catalog row for one stored file. Bytes live under ATTACHMENT_ROOT."""

    __tablename__ = "attachment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str] = mapped_column(String(32))
    byte_size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionTargetRow(Base):
    """Named SSH/Docker command destinations owned by one Supabase user."""

    __tablename__ = "execution_target"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_execution_target_user_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))
    spec_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
