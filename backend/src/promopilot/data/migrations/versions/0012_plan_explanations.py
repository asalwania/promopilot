"""Plan explanations (E8 #49, ADR 0050).

- `plan_revisions.explanation`: the Explainer's summary, one rationale per plan line, who wrote
  them (the LLM or the template) and why the template was used; null until the Explainer has
  run, and for revisions planned before #49.

Revision ID: 0012
Revises: 0009
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_revisions", sa.Column("explanation", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("plan_revisions", "explanation")
