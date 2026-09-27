"""Clearance shortfalls and policy findings on plan revisions (E6, ADR 0040).

Both columns are nullable: revisions planned before #36 have neither.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("clearance_shortfalls", postgresql.JSONB))
    op.add_column("plan_revisions", sa.Column("policy_findings", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "policy_findings")
    op.drop_column("plan_revisions", "clearance_shortfalls")
