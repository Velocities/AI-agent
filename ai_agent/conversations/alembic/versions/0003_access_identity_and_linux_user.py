"""Deployment access: JWT profile fields and Linux execution user.

Revision ID: 0003_access_identity
Revises: 0002_deployment_access
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_access_identity"
down_revision: Union[str, Sequence[str], None] = "0002_deployment_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("deployment_access") as batch:
        batch.add_column(
            sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        )
        batch.add_column(
            sa.Column("linux_username", sa.String(length=64), nullable=False, server_default=""),
        )


def downgrade() -> None:
    with op.batch_alter_table("deployment_access") as batch:
        batch.drop_column("linux_username")
        batch.drop_column("email")
