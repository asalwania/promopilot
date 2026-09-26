"""A deliberately naive greedy planner: the walking skeleton's placeholder until E6's optimiser.

Each in-scope (SKU, region) gets one PCT_OFF option at a fixed depth from the start of the
promo window, offered to All customers. Expected units are recent average sales (no uplift
model yet), so each line's expected incremental profit is minus its promo cost. Options are
ranked by base margin and added while total promo cost stays within the marketing budget.
"""

from collections import defaultdict
from collections.abc import Mapping
from typing import cast

import pandas as pd

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    Segment,
    TargetSegment,
)
from promopilot.economics import (
    discount_funding,
    effective_unit_price,
    fixed_marketing_cost,
    gross_profit,
    incremental_profit,
    margin,
    promo_cost,
)

DEPTH_PCT = 20
MAX_DURATION_WEEKS = 4
RECENT_WEEKS = 8
"""Expected units are the average weekly sales over this many weeks before the as-of week."""


def recent_sales_since(as_of_week: int) -> int:
    return max(as_of_week - RECENT_WEEKS, 0)


def naive_plan(
    request: PlanningRequest,
    *,
    products: pd.DataFrame,
    stores: pd.DataFrame,
    recent_sales: pd.DataFrame,
    policy: CompanyPolicy,
) -> PlanRevision:
    """Plan revision 1 for `request`. `recent_sales` holds the weeks since `recent_sales_since`."""
    window = request.promo_window
    duration = min(window.end_week - window.start_week + 1, MAX_DURATION_WEEKS)
    depth = min(DEPTH_PCT, policy.max_discount_pct)
    weekly = _weekly_units_by_segment(recent_sales, stores, request.as_of_week)

    in_scope = products[products["category"].isin(request.scope.categories)]
    if request.scope.sku_ids:
        in_scope = in_scope[in_scope["sku_id"].isin(request.scope.sku_ids)]

    options = []
    catalogue = zip(
        in_scope["sku_id"].astype(str).tolist(),
        in_scope["base_price"].astype(float).tolist(),
        in_scope["unit_cost"].astype(float).tolist(),
        strict=True,
    )
    for sku_id, base_price, unit_cost in catalogue:
        for region in request.scope.regions:
            per_week = weekly.get((sku_id, region), {})
            units_by_segment = {segment: units * duration for segment, units in per_week.items()}
            units = sum(units_by_segment.values())
            price = effective_unit_price(Mechanism.PCT_OFF, base_price, depth)
            funding = discount_funding(
                base_price, price, units_by_segment, TargetSegment.ALL_CUSTOMERS
            )
            fixed = fixed_marketing_cost(Mechanism.PCT_OFF, duration, policy)
            line = PlanLine(
                sku_id=sku_id,
                region=region,
                mechanism=Mechanism.PCT_OFF,
                depth_pct=depth,
                duration_weeks=duration,
                start_week=window.start_week,
                target_segment=TargetSegment.ALL_CUSTOMERS,
            )
            planned = PlanRevisionLine(
                line=line,
                expected_units=units,
                promo_cost=promo_cost(funding, Mechanism.PCT_OFF, duration, policy),
                expected_incremental_profit=incremental_profit(
                    gross_profit(units, price, unit_cost),
                    gross_profit(units, base_price, unit_cost),
                    fixed,
                ),
            )
            options.append((margin(base_price, unit_cost), planned))

    options.sort(key=lambda option: (-option[0], option[1].line.sku_id, option[1].line.region))
    chosen, spent = [], 0.0
    for _, planned in options:
        if spent + planned.promo_cost <= request.marketing_budget:
            chosen.append(planned)
            spent += planned.promo_cost
    return PlanRevision(number=1, lines=tuple(chosen))


def _weekly_units_by_segment(
    recent_sales: pd.DataFrame, stores: pd.DataFrame, as_of_week: int
) -> dict[tuple[str, Region], dict[Segment, float]]:
    """Average weekly units per (SKU, region) and segment, summed over the region's stores."""
    weeks = as_of_week - recent_sales_since(as_of_week)
    region_of = dict(zip(stores["store_id"], stores["region"], strict=True))
    totals: dict[tuple[str, Region], dict[Segment, float]] = defaultdict(
        lambda: dict.fromkeys(Segment, 0.0)
    )
    rows = zip(
        recent_sales["sku_id"].tolist(),
        recent_sales["store_id"].tolist(),
        recent_sales["segment_units"].tolist(),
        strict=True,
    )
    for sku_id, store_id, segment_units in rows:
        key = (str(sku_id), Region(region_of[store_id]))
        for segment, units in cast(Mapping[str, float], segment_units).items():
            totals[key][Segment(segment)] += units / weeks
    return totals
