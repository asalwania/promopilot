"""The SPEC §8.2 data tables and the app-state tables (SQLAlchemy Core).

Migrations in migrations/ create them.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = MetaData()

products = Table(
    "products",
    metadata,
    Column("sku_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("brand", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("subcategory", Text, nullable=False),
    Column("pack_size", Text, nullable=False),
    Column("base_price", Float, nullable=False),
    Column("unit_cost", Float, nullable=False),
    Column("is_kvi", Boolean, nullable=False),
)

stores = Table(
    "stores",
    metadata,
    Column("store_id", Text, primary_key=True),
    Column("region", Text, nullable=False),
    Column("city", Text, nullable=False),
    Column("segment_mix", JSONB, nullable=False),
)

calendar = Table(
    "calendar",
    metadata,
    Column("week_id", Integer, primary_key=True),
    Column("region", Text, primary_key=True),
    Column("week_start", Date, nullable=False),
    Column("holiday_name", Text),
    Column("holiday_intensity", Float, nullable=False),
)

sales_weekly = Table(
    "sales_weekly",
    metadata,
    Column("week_id", Integer, primary_key=True),
    Column("store_id", Text, ForeignKey("stores.store_id"), primary_key=True),
    Column("sku_id", Text, ForeignKey("products.sku_id"), primary_key=True),
    Column("units", Integer, nullable=False),
    Column("price_paid", Float, nullable=False),
    Column("on_promo", Boolean, nullable=False),
    Column("mechanism", Text),
    Column("depth", Integer),
    Column("target_segment", Text),
    Column("segment_units", JSONB, nullable=False),
    Index("ix_sales_weekly_sku_id", "sku_id"),
)

promotions_history = Table(
    "promotions_history",
    metadata,
    Column("promo_id", Text, primary_key=True),
    Column("sku_id", Text, ForeignKey("products.sku_id"), nullable=False),
    Column("region", Text, nullable=False),
    Column("mechanism", Text, nullable=False),
    Column("depth", Integer, nullable=False),
    Column("start_week", Integer, nullable=False),
    Column("duration", Integer, nullable=False),
    Column("target_segment", Text, nullable=False),
    Column("bundle_sku_id", Text, ForeignKey("products.sku_id")),
)

inventory = Table(
    "inventory",
    metadata,
    Column("snapshot_week", Integer, primary_key=True),
    Column("store_id", Text, ForeignKey("stores.store_id"), primary_key=True),
    Column("sku_id", Text, ForeignKey("products.sku_id"), primary_key=True),
    Column("on_hand", Integer, nullable=False),
    Column("on_order", Integer, nullable=False),
    Column("safety_stock", Integer, nullable=False),
    Column("is_overstock", Boolean, nullable=False),
    Column("days_of_cover", Float, nullable=False),
)

competitor_prices = Table(
    "competitor_prices",
    metadata,
    Column("week_id", Integer, primary_key=True),
    Column("region", Text, primary_key=True),
    Column("sku_id", Text, ForeignKey("products.sku_id"), primary_key=True),
    Column("competitor_price", Float, nullable=False),
    Column("competitor_on_promo", Boolean, nullable=False),
)

baskets = Table(
    "baskets",
    metadata,
    Column("basket_id", Text, primary_key=True),
    Column("store_id", Text, ForeignKey("stores.store_id"), nullable=False),
    Column("week_id", Integer, nullable=False),
    Column("segment", Text, nullable=False),
    Column("sku_ids", ARRAY(Text), nullable=False),
    Index("ix_baskets_week_id", "week_id"),
)

DATA_TABLES = [
    products,
    stores,
    calendar,
    sales_weekly,
    promotions_history,
    inventory,
    competitor_prices,
    baskets,
]
"""In load order: referenced tables first."""

# App state (E3): planning sessions and their plan revisions. No foreign keys into the data
# tables, so reloading the data (TRUNCATE ... CASCADE) never deletes a session.

planning_sessions = Table(
    "planning_sessions",
    metadata,
    Column("id", UUID, primary_key=True),
    Column("brief", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("planning_request", JSONB),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_planning_sessions_status", "status"),
)

plan_revisions = Table(
    "plan_revisions",
    metadata,
    Column("session_id", UUID, ForeignKey("planning_sessions.id"), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

plan_lines = Table(
    "plan_lines",
    metadata,
    Column("session_id", UUID, primary_key=True),
    Column("revision_number", Integer, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("sku_id", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("mechanism", Text, nullable=False),
    Column("depth_pct", Integer, nullable=False),
    Column("duration_weeks", Integer, nullable=False),
    Column("start_week", Integer, nullable=False),
    Column("target_segment", Text, nullable=False),
    Column("bundle_partner_sku_id", Text),
    Column("expected_units", Float, nullable=False),
    Column("promo_cost", Float, nullable=False),
    Column("expected_incremental_profit", Float, nullable=False),
    ForeignKeyConstraint(
        ["session_id", "revision_number"],
        ["plan_revisions.session_id", "plan_revisions.number"],
    ),
)
