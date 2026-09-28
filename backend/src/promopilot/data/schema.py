"""The SPEC §8.2 data tables and the app-state tables (SQLAlchemy Core).

Migrations in migrations/ create them.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
    UniqueConstraint,
    func,
    text,
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
    # E8 (ADR 0046): the agent graph's checkpoint thread; null for sessions planned before it.
    Column("thread_id", Text),
    # E8 #46 (ADR 0048): the Context agent's latest reading, its open questions and every answer.
    Column("assumptions", JSONB),
    Column("questions", JSONB),
    Column("clarifications", JSONB),
    # E8 #50 (ADR 0052): every amendment, oldest first.
    Column("amendments", JSONB),
    Index("ix_planning_sessions_status", "status"),
)

plan_revisions = Table(
    "plan_revisions",
    metadata,
    Column("session_id", UUID, ForeignKey("planning_sessions.id"), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # E6 (ADR 0038); null for revisions planned before the optimiser.
    Column("solver_status", Text),
    Column("objective", Float),
    Column("binding_constraints", JSONB),
    Column("not_selected", JSONB),
    # E7 (ADR 0042); null for revisions planned before the simulator.
    Column("simulation", JSONB),
    # E6 #36 (ADR 0040); null for revisions planned before it.
    Column("clearance_shortfalls", JSONB),
    Column("policy_findings", JSONB),
    # E6 #37 (ADR 0044); null unless the request is infeasible (or not proven feasible).
    Column("relaxation", JSONB),
    # E8 #44 (ADR 0046): violations the Critic left open; null for revisions planned before it.
    Column("open_issues", JSONB),
    # E8 #49 (ADR 0050): the Explainer's summary and rationales; null until it has run.
    Column("explanation", JSONB),
    # E8 #50 (ADR 0052): the diff from the previous revision; null for the first.
    Column("diff", JSONB),
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
    Column("why_chosen", JSONB),
    Column("mechanism_comparison", JSONB),
    Column("baseline_units", Float),
    Column("uplift_pct", Float),
    Column("segments", JSONB),
    Column("cross_effects", JSONB),
    ForeignKeyConstraint(
        ["session_id", "revision_number"],
        ["plan_revisions.session_id", "plan_revisions.number"],
    ),
)

# Every approval and rejection of a plan revision, in order: the session's audit trail (E8,
# ADR 0046). A session has at most one approval.

approvals = Table(
    "approvals",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("session_id", UUID, nullable=False),
    Column("revision_number", Integer, nullable=False),
    Column("decision", Text, nullable=False),
    Column("reason", Text),
    Column("decided_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["session_id", "revision_number"],
        ["plan_revisions.session_id", "plan_revisions.number"],
    ),
    CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approvals_decision"),
    CheckConstraint("(decision = 'rejected') = (reason IS NOT NULL)", name="ck_approvals_reason"),
    Index("ix_approvals_session_id", "session_id"),
    Index(
        "uq_approvals_one_approval",
        "session_id",
        unique=True,
        postgresql_where=text("decision = 'approved'"),
    ),
)

# Every step of a planning session's agent graph, numbered 1, 2, ... within the session: the
# SSE trace (E8 #45, ADR 0047).

trace_events = Table(
    "trace_events",
    metadata,
    Column("session_id", UUID, ForeignKey("planning_sessions.id"), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("node", Text),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("seq >= 1", name="ck_trace_events_seq"),
)

# Model registry (E4): one row per trained model version; the artifact is a file under
# MODEL_DIR, and artifact_path is relative to it (ADR 0023).

model_registry = Table(
    "model_registry",
    metadata,
    Column("model_id", UUID, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("trained_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("as_of_week", Integer, nullable=False),
    Column("metrics", JSONB, nullable=False),
    Column("artifact_path", Text, nullable=False),
    UniqueConstraint("kind", "version", name="uq_model_registry_kind_version"),
)
