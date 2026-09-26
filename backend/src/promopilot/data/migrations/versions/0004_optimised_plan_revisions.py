"""Optimised plan revisions (E6): solver status, objective, binding constraints, the options
left out, and why each plan line was chosen (ADR 0038).

Every new column is nullable: revisions planned before the optimiser (E3) have none.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("solver_status", sa.Text))
    op.add_column("plan_revisions", sa.Column("objective", sa.Float))
    op.add_column("plan_revisions", sa.Column("binding_constraints", postgresql.JSONB))
    op.add_column("plan_revisions", sa.Column("not_selected", postgresql.JSONB))
    op.add_column("plan_lines", sa.Column("why_chosen", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_lines", "why_chosen")
    op.drop_column("plan_revisions", "not_selected")
    op.drop_column("plan_revisions", "binding_constraints")
    op.drop_column("plan_revisions", "objective")
    op.drop_column("plan_revisions", "solver_status")
