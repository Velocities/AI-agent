"""User settings and attachment catalog.

Revision ID: 0006_user_settings_and_attachments
Revises: 0005_monitoring_admin
Create Date: 2026-10-23

`user_setting` holds per-user preferences. A missing row means
strip_image_metadata is on. `attachment` records kind, type, size, and
checksum. File bytes live on disk, not in this table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_user_settings_and_attachments"
down_revision: Union[str, Sequence[str], None] = "0005_monitoring_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_setting",
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("strip_image_metadata", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "attachment",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_attachment_user_id", "attachment", ["user_id"])
    op.create_index(
        "ix_attachment_user_conversation",
        "attachment",
        ["user_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_attachment_user_conversation", table_name="attachment")
    op.drop_index("ix_attachment_user_id", table_name="attachment")
    op.drop_table("attachment")
    op.drop_table("user_setting")
