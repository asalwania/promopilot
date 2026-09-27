"""The relaxation of an infeasible request on plan revisions (E6 #37, ADR 0044).

Nullable: only a request no plan can reach every clearance target of has one, and revisions
planned before #37 have none.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("relaxation", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "relaxation")
