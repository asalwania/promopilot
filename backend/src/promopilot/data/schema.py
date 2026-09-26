"""The SPEC §8.2 data tables (SQLAlchemy Core). Migrations in migrations/ create them."""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

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
