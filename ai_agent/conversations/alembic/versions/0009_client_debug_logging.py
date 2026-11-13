"""Client debug logging on user_setting.

Revision ID: 0009_client_debug_logging
Revises: 0008_speech_personalization
Create Date: 2026-11-12

Null client_debug_logging means the client does not send debug logs.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_client_debug_logging"
down_revision: Union[str, Sequence[str], None] = "0008_speech_personalization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.add_column(sa.Column("client_debug_logging", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.drop_column("client_debug_logging")
