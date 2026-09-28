"""Trace events (E8 #45, ADR 0047): every step of a planning session's agent graph, in order.

Each event is numbered 1, 2, ... within its session (`seq`, the SSE event id); its payload is
the typed event as JSON, and `kind` repeats the payload's kind for queries.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_events",
        sa.Column(
            "session_id",
            postgresql.UUID,
            sa.ForeignKey("planning_sessions.id"),
            primary_key=True,
        ),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("node", sa.Text),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("seq >= 1", name="ck_trace_events_seq"),
    )


def downgrade() -> None:
    op.drop_table("trace_events")
