"""Approvals, open issues and the agent graph's thread (E8 #44, ADR 0046).

- `approvals`: every approval and rejection of a plan revision, in order; at most one approval
  per session.
- `planning_sessions.thread_id`: the agent graph's checkpoint thread; null for sessions
  planned before E8.
- `plan_revisions.open_issues`: violations the Critic left open; null before E8.

LangGraph's checkpoint tables are not here: `AsyncPostgresSaver.setup()` creates and migrates
them at API startup.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("planning_sessions", sa.Column("thread_id", sa.Text))
    op.add_column("plan_revisions", sa.Column("open_issues", postgresql.JSONB))
    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("session_id", postgresql.UUID, nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "revision_number"],
            ["plan_revisions.session_id", "plan_revisions.number"],
        ),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approvals_decision"),
        sa.CheckConstraint(
            "(decision = 'rejected') = (reason IS NOT NULL)", name="ck_approvals_reason"
        ),
    )
    op.create_index("ix_approvals_session_id", "approvals", ["session_id"])
    op.create_index(
        "uq_approvals_one_approval",
        "approvals",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("decision = 'approved'"),
    )


def downgrade() -> None:
    op.drop_table("approvals")
    op.drop_column("plan_revisions", "open_issues")
    op.drop_column("planning_sessions", "thread_id")
