"""Retail data tables (SPEC §8.2): products, stores, calendar, sales, promotions,
inventory, competitor prices and baskets.

Revision ID: 0001
Revises:
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("sku_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("brand", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("subcategory", sa.Text, nullable=False),
        sa.Column("pack_size", sa.Text, nullable=False),
        sa.Column("base_price", sa.Float, nullable=False),
        sa.Column("unit_cost", sa.Float, nullable=False),
        sa.Column("is_kvi", sa.Boolean, nullable=False),
    )
    op.create_table(
        "stores",
        sa.Column("store_id", sa.Text, primary_key=True),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("city", sa.Text, nullable=False),
        sa.Column("segment_mix", postgresql.JSONB, nullable=False),
    )
    op.create_table(
        "calendar",
        sa.Column("week_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.Text, primary_key=True),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("holiday_name", sa.Text),
        sa.Column("holiday_intensity", sa.Float, nullable=False),
    )
    op.create_table(
        "sales_weekly",
        sa.Column("week_id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Text, sa.ForeignKey("stores.store_id"), primary_key=True),
        sa.Column("sku_id", sa.Text, sa.ForeignKey("products.sku_id"), primary_key=True),
        sa.Column("units", sa.Integer, nullable=False),
        sa.Column("price_paid", sa.Float, nullable=False),
        sa.Column("on_promo", sa.Boolean, nullable=False),
        sa.Column("mechanism", sa.Text),
        sa.Column("depth", sa.Integer),
        sa.Column("target_segment", sa.Text),
        sa.Column("segment_units", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_sales_weekly_sku_id", "sales_weekly", ["sku_id"])
    op.create_table(
        "promotions_history",
        sa.Column("promo_id", sa.Text, primary_key=True),
        sa.Column("sku_id", sa.Text, sa.ForeignKey("products.sku_id"), nullable=False),
        sa.Column("region", sa.Text, nullable=False),
        sa.Column("mechanism", sa.Text, nullable=False),
        sa.Column("depth", sa.Integer, nullable=False),
        sa.Column("start_week", sa.Integer, nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("target_segment", sa.Text, nullable=False),
        sa.Column("bundle_sku_id", sa.Text, sa.ForeignKey("products.sku_id")),
    )
    op.create_table(
        "inventory",
        sa.Column("snapshot_week", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Text, sa.ForeignKey("stores.store_id"), primary_key=True),
        sa.Column("sku_id", sa.Text, sa.ForeignKey("products.sku_id"), primary_key=True),
        sa.Column("on_hand", sa.Integer, nullable=False),
        sa.Column("on_order", sa.Integer, nullable=False),
        sa.Column("safety_stock", sa.Integer, nullable=False),
        sa.Column("is_overstock", sa.Boolean, nullable=False),
        sa.Column("days_of_cover", sa.Float, nullable=False),
    )
    op.create_table(
        "competitor_prices",
        sa.Column("week_id", sa.Integer, primary_key=True),
        sa.Column("region", sa.Text, primary_key=True),
        sa.Column("sku_id", sa.Text, sa.ForeignKey("products.sku_id"), primary_key=True),
        sa.Column("competitor_price", sa.Float, nullable=False),
        sa.Column("competitor_on_promo", sa.Boolean, nullable=False),
    )
    op.create_table(
        "baskets",
        sa.Column("basket_id", sa.Text, primary_key=True),
        sa.Column("store_id", sa.Text, sa.ForeignKey("stores.store_id"), nullable=False),
        sa.Column("week_id", sa.Integer, nullable=False),
        sa.Column("segment", sa.Text, nullable=False),
        sa.Column("sku_ids", postgresql.ARRAY(sa.Text), nullable=False),
    )
    op.create_index("ix_baskets_week_id", "baskets", ["week_id"])


def downgrade() -> None:
    for table in [
        "baskets",
        "competitor_prices",
        "inventory",
        "promotions_history",
        "sales_weekly",
        "calendar",
        "stores",
        "products",
    ]:
        op.drop_table(table)
