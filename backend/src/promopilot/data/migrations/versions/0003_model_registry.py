"""The model registry (E4): one row per trained model version.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_id", postgresql.UUID, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("as_of_week", sa.Integer, nullable=False),
        sa.Column("metrics", postgresql.JSONB, nullable=False),
        sa.Column("artifact_path", sa.Text, nullable=False),
        sa.UniqueConstraint("kind", "version", name="uq_model_registry_kind_version"),
    )


def downgrade() -> None:
    op.drop_table("model_registry")
