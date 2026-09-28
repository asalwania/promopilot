"""Amendments of a planning session and each plan revision's diff (E8 #50, ADR 0052).

- `planning_sessions.amendments`: every amendment, oldest first: its text, the revision it
  amended, the relaxation it accepts (if any) and when it was made.
- `plan_revisions.diff`: what changed from the previous plan revision; null for the first.

Both are JSONB and null for sessions and revisions planned before #50.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("planning_sessions", sa.Column("amendments", postgresql.JSONB))
    op.add_column("plan_revisions", sa.Column("diff", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "diff")
    op.drop_column("planning_sessions", "amendments")
