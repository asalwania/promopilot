"""The baseline forecast: no-promotion units per store x SKU x segment x week (SPEC §9.1)."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from promopilot.models import demand
from promopilot.models.demand import DemandHistory, DemandModel

AS_OF = 52  # the first week after the small world's 52 history weeks
DIWALI_NORTH = 55  # Diwali 2025, full intensity in North (datagen/config.yaml)
QUIET_WEEK = 58  # no festival in North or South


@pytest.fixture(scope="module")
def model(small_history: DemandHistory) -> DemandModel:
    return demand.fit(small_history, as_of_week=AS_OF, seed=7)


def test_festival_weeks_raise_the_baseline(model: DemandModel) -> None:
    forecast = model.baseline([DIWALI_NORTH, QUIET_WEEK], regions=["North"])

    units = forecast.groupby("week_id")["units"].sum()
    assert units[DIWALI_NORTH] > 1.1 * units[QUIET_WEEK]


def poisoned(history: DemandHistory, as_of_week: int) -> DemandHistory:
    """Adds absurd rows at and after the as-of week: sales, promotions and competitor prices."""
    sales = history.sales_weekly
    future_sales = sales[sales["week_id"] >= as_of_week - 4].copy()
    future_sales["week_id"] += 4
    future_sales["units"] = 10_000
    future_sales["segment_units"] = pd.Series(
        [dict.fromkeys(units, 2_500) for units in future_sales["segment_units"]],
        index=future_sales.index,
    )
    promotions = history.promotions_history
    future_promotions = promotions.tail(20).copy()
    future_promotions["promo_id"] += "-future"
    future_promotions["start_week"] = as_of_week + future_promotions.index % 3
    competitors = history.competitor_prices
    future_competitors = competitors[competitors["week_id"] == as_of_week - 1].copy()
    future_competitors["week_id"] = as_of_week
    future_competitors["competitor_price"] = 0.01
    return DemandHistory(
        products=history.products,
        stores=history.stores,
        calendar=history.calendar,
        sales_weekly=pd.concat([sales, future_sales]),
        promotions_history=pd.concat([promotions, future_promotions]),
        competitor_prices=pd.concat([competitors, future_competitors]),
    )


def test_fitting_ignores_rows_at_or_after_the_as_of_week(
    small_history: DemandHistory, model: DemandModel
) -> None:
    leaky = demand.fit(poisoned(small_history, AS_OF), as_of_week=AS_OF, seed=7)

    weeks = [AS_OF, AS_OF + 3]
    assert_frame_equal(leaky.baseline(weeks), model.baseline(weeks))
    assert leaky.metrics == model.metrics


def test_fitting_is_deterministic_for_a_seed(
    small_history: DemandHistory, model: DemandModel
) -> None:
    again = demand.fit(small_history, as_of_week=AS_OF, seed=7)
    reseeded = demand.fit(small_history, as_of_week=AS_OF, seed=8)

    weeks = [AS_OF, DIWALI_NORTH]
    assert_frame_equal(again.baseline(weeks), model.baseline(weeks))
    assert not reseeded.baseline(weeks)["units"].equals(model.baseline(weeks)["units"])


def test_the_holdout_wape_is_reported_at_the_model_store_and_region_grains(
    model: DemandModel,
) -> None:
    wape = model.metrics

    assert set(wape) == {"baseline_wape", "baseline_wape_store_sku", "baseline_wape_region_sku"}
    assert all(0 < value < 1 for value in wape.values())
    # Summing segments and stores averages noise out.
    assert wape["baseline_wape_region_sku"] < wape["baseline_wape_store_sku"]
    assert wape["baseline_wape_store_sku"] < wape["baseline_wape"]
