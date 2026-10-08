"""Monitoring admin allowlist.

Revision ID: 0005_monitoring_admin
Revises: 0004_execution_targets
Create Date: 2026-10-07

Who may open host monitoring. Not the same as deployment_access.
See ai_agent/deployment/monitoring_admin_store.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_monitoring_admin"
down_revision: Union[str, Sequence[str], None] = "0004_execution_targets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitoring_admin",
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("monitoring_admin")
