"""The safety margin a plan revision was planned with (E9, #159, ADR 0080): its budget, stock
and margin quantiles, its promo cost as budgeted, and whether the budget margin was waived for
the brief's clearance targets.

The column is nullable: revisions planned before #159 have none.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("safety_margin", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "safety_margin")
