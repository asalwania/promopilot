"""Plan-line uplift and cross effects (E10, #60): each plan line's baseline and uplift, its
units by segment, and the other SKUs it moves in its region (ADR 0060).

The columns are nullable: plan lines planned before #60 have none.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_lines", sa.Column("baseline_units", sa.Float))
    op.add_column("plan_lines", sa.Column("uplift_pct", sa.Float))
    op.add_column("plan_lines", sa.Column("segments", postgresql.JSONB))
    op.add_column("plan_lines", sa.Column("cross_effects", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_lines", "cross_effects")
    op.drop_column("plan_lines", "segments")
    op.drop_column("plan_lines", "uplift_pct")
    op.drop_column("plan_lines", "baseline_units")
