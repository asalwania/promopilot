"""App-state tables (E3): planning sessions, plan revisions and plan lines.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "planning_sessions",
        sa.Column("id", postgresql.UUID, primary_key=True),
        sa.Column("brief", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("planning_request", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_planning_sessions_status", "planning_sessions", ["status"])
    op.create_table(
        "plan_revisions",
        sa.Column(
            "session_id",
            postgresql.UUID,
            sa.ForeignKey("planning_sessions.id"),
            primary_key=True,
        ),
        sa.Column("number", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_table(
        "plan_lines",
        sa.Column("session_id", postgresql.UUID, primary_key=True),
        sa.Column("revision_number", sa.Integer, primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("sku_id", sa.Text, nullable=False),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("mechanism", sa.Text, nullable=False),
        sa.Column("depth_pct", sa.Integer, nullable=False),
        sa.Column("duration_weeks", sa.Integer, nullable=False),
        sa.Column("start_week", sa.Integer, nullable=False),
        sa.Column("target_segment", sa.Text, nullable=False),
        sa.Column("bundle_partner_sku_id", sa.Text),
        sa.Column("expected_units", sa.Float, nullable=False),
        sa.Column("promo_cost", sa.Float, nullable=False),
        sa.Column("expected_incremental_profit", sa.Float, nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id", "revision_number"],
            ["plan_revisions.session_id", "plan_revisions.number"],
        ),
    )


def downgrade() -> None:
    op.drop_table("plan_lines")
    op.drop_table("plan_revisions")
    op.drop_index("ix_planning_sessions_status", "planning_sessions")
    op.drop_table("planning_sessions")
