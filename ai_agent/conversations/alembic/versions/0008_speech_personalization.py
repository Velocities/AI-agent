"""Speech choices on user_setting.

Revision ID: 0008_speech_personalization
Revises: 0007_user_personalization
Create Date: 2026-10-30

Null transcription means Google remote. Null phrases mean the Hey/Bye defaults.
Null voice_command_approval means voice confirmation of commands is off.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_speech_personalization"
down_revision: Union[str, Sequence[str], None] = "0007_user_personalization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.add_column(sa.Column("stt_provider", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("wake_phrase", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("close_phrase", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("voice_command_approval", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_setting") as batch:
        batch.drop_column("voice_command_approval")
        batch.drop_column("close_phrase")
        batch.drop_column("wake_phrase")
        batch.drop_column("stt_provider")
