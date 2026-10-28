"""Per-user personalization on user_setting.

Revision ID: 0007_user_personalization
Revises: 0006_user_settings_and_attachments
Create Date: 2026-10-27

Null means the default: no name, normal replies, no timezone, no coding notes.
A missing user_setting row still means strip_image_metadata is on.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_user_personalization"
down_revision: Union[str, Sequence[str], None] = "0006_user_settings_and_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.add_column(sa.Column("agent_name", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("agent_name_pronunciation", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("user_name", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("user_name_pronunciation", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("coding_preferences", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reply_length", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.drop_column("timezone")
        batch.drop_column("reply_length")
        batch.drop_column("coding_preferences")
        batch.drop_column("user_name_pronunciation")
        batch.drop_column("user_name")
        batch.drop_column("agent_name_pronunciation")
        batch.drop_column("agent_name")
