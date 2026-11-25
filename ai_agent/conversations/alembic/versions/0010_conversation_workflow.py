"""Workflow name and parameters on a conversation.

Revision ID: 0010_conversation_workflow
Revises: 0009_client_debug_logging
Create Date: 2026-11-17

Null workflow_name means an ordinary chat. Parameters are the session
values, not part of the image.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_conversation_workflow"
down_revision: Union[str, Sequence[str], None] = "0009_client_debug_logging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("workflow_name", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("workflow_parameters", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("workflow_parameters")
        batch.drop_column("workflow_name")
