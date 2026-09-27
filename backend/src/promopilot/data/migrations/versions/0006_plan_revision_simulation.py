"""The Monte Carlo simulation of each plan revision (E7, ADR 0042).

The column is nullable: revisions planned before the simulator have none.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("simulation", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "simulation")
