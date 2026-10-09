"""Per-user execution targets (SSH/Docker metadata).

Revision ID: 0004_execution_targets
Revises: 0003_access_identity
Create Date: 2026-10-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_execution_targets"
down_revision: Union[str, Sequence[str], None] = "0003_access_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_target",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_execution_target_user_name"),
    )
    op.create_index("ix_execution_target_user_id", "execution_target", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_target_user_id", table_name="execution_target")
    op.drop_table("execution_target")
