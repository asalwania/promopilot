"""Assumptions and clarifications of a planning session (E8 #46, ADR 0048).

- `planning_sessions.assumptions`: how the Context agent read the brief, from its latest
  reading.
- `planning_sessions.questions`: the clarification questions waiting for an answer.
- `planning_sessions.clarifications`: every question answered so far, oldest first.

All are JSONB and null for sessions planned before #46.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("planning_sessions", sa.Column("assumptions", postgresql.JSONB))
    op.add_column("planning_sessions", sa.Column("questions", postgresql.JSONB))
    op.add_column("planning_sessions", sa.Column("clarifications", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("planning_sessions", "clarifications")
    op.drop_column("planning_sessions", "questions")
    op.drop_column("planning_sessions", "assumptions")
