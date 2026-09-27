"""Mechanism comparisons (E7): each plan line's comparison of mechanisms (ADR 0041).

The column is nullable: plan lines planned before E7 have none.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_lines", sa.Column("mechanism_comparison", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_lines", "mechanism_comparison")
