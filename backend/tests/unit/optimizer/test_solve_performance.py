"""The optimiser on the demo scope (E6 exit, ADR 0038): 2 regions x 2 categories of the seed-42
default world, planned around Diwali, in under 10 seconds.

The timing covers everything `solve` does: pricing the pairwise terms, the solve itself,
the re-solves that find the binding constraints, and the not-selected list. Fitting the
models and generating the options are not timed. The test asserts nothing about seed-42's
numbers, which change whenever the synthetic world is retuned.
"""

import time

import pytest

from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, PlanningRequest, PromoWindow, Region, Scope
from promopilot.models import demand, relations
from promopilot.optimizer import (
    FittedOptionFacts,
    OptionContext,
    SolverSettings,
    generate_options,
    solve,
)
from tests.conftest import history_of

LIMIT_SECONDS = 10.0


def diwali_week(dataset: GeneratedDataset, after: int) -> int:
    calendar = dataset.calendar
    festival = calendar[
        (calendar["week_id"] > after + 1)
        & calendar["holiday_name"].fillna("").str.contains("Diwali")
    ]
    return int(festival["week_id"].min())


@pytest.mark.model
def test_the_optimiser_plans_the_demo_scope_in_under_ten_seconds(
    default_dataset: GeneratedDataset,
) -> None:
    history = history_of(default_dataset)
    as_of = int(history.sales_weekly["week_id"].max()) + 1
    model = demand.fit(history, as_of_week=as_of, seed=7)
    found = relations.fit(history, default_dataset.baskets, model, as_of_week=as_of, seed=7)
    policy = CompanyPolicy()
    snapshot = default_dataset.inventory
    snapshot = snapshot[snapshot["snapshot_week"] == as_of - 1]
    context = OptionContext(
        demand_model=model,
        relations=found,
        products=default_dataset.products,
        stock=pooled_stock(snapshot, default_dataset.stores, policy),
        policy=policy,
    )
    diwali = diwali_week(default_dataset, as_of)
    request = PlanningRequest(
        as_of_week=as_of,
        scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
        promo_window=PromoWindow(start_week=diwali - 1, end_week=diwali),
        marketing_budget=200_000.0,
    )
    options = generate_options(request, context)

    started = time.perf_counter()
    result = solve(
        request,
        options,
        FittedOptionFacts(context),
        policy,
        settings=SolverSettings(time_limit_seconds=LIMIT_SECONDS),
        seed=0,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < LIMIT_SECONDS
    assert len(result.why_chosen) == len(result.plan.lines)
    assert len(result.not_selected) <= 5
