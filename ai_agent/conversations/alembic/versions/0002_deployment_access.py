"""Deployment access whitelist.

Revision ID: 0002_deployment_access
Revises: 0001_conversations
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_deployment_access"
down_revision: Union[str, Sequence[str], None] = "0001_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deployment_access",
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deployment_access_status", "deployment_access", ["status"])


def downgrade() -> None:
    op.drop_index("ix_deployment_access_status", table_name="deployment_access")
    op.drop_table("deployment_access")
