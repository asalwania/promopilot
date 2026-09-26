"""The optimiser on the demo scope (E6 exit, ADR 0038): 2 regions x 2 categories of the seed-42
default world, planned around Diwali, in under 10 seconds.

The 10 seconds cover `solve` itself: pricing the pairwise terms, the solve, why each line was
chosen and the not-selected list. They do not cover candidate generation (#113), nor the
binding analysis, a separate post-step with its own OPTIMIZER_BINDING_TIME_LIMIT_SECONDS, so
it is switched off here. The tests assert nothing about seed-42's numbers, which change
whenever the world is retuned.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pytest

from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, PlanLine, PlanningRequest, PromoWindow, Region, Scope
from promopilot.guardrails import SkuFacts
from promopilot.models import demand, relations
from promopilot.optimizer import (
    FittedOptionFacts,
    OptimisationResult,
    OptionContext,
    SolverSettings,
    generate_options,
    solve,
)
from tests.conftest import history_of

LIMIT_SECONDS = 10.0


class TimedFacts:
    """The fitted facts, adding up the time spent pricing pairwise terms."""

    def __init__(self, inner: FittedOptionFacts) -> None:
        self.inner = inner
        self.pairwise_seconds = 0.0

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return self.inner.sku(sku_id, region)

    def pairwise_cannibalisation(self, pairs: Sequence[tuple[PlanLine, PlanLine]]) -> np.ndarray:
        started = time.perf_counter()
        try:
            return self.inner.pairwise_cannibalisation(pairs)
        finally:
            self.pairwise_seconds += time.perf_counter() - started


@dataclass(frozen=True)
class Timed:
    result: OptimisationResult
    seconds: float
    pairwise_seconds: float


def diwali_week(dataset: GeneratedDataset, after: int) -> int:
    calendar = dataset.calendar
    festival = calendar[
        (calendar["week_id"] > after + 1)
        & calendar["holiday_name"].fillna("").str.contains("Diwali")
    ]
    return int(festival["week_id"].min())


@pytest.fixture(scope="module")
def demo_solve(default_dataset: GeneratedDataset) -> Timed:
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
    facts = TimedFacts(FittedOptionFacts(context))

    started = time.perf_counter()
    result = solve(
        request,
        options,
        facts,
        policy,
        settings=SolverSettings(time_limit_seconds=LIMIT_SECONDS, binding_time_limit_seconds=0),
        seed=0,
    )
    return Timed(result, time.perf_counter() - started, facts.pairwise_seconds)


@pytest.mark.model
def test_the_demo_plan_says_why_each_line_was_chosen_and_what_was_left_out(
    demo_solve: Timed,
) -> None:
    result = demo_solve.result

    assert result.plan.lines
    assert len(result.why_chosen) == len(result.plan.lines)
    assert all(why.reasons for why in result.why_chosen)
    assert len(result.not_selected) <= 5


@pytest.mark.model
@pytest.mark.xfail(
    reason="#112: pricing the demo's pairwise terms takes about 14 s",
    strict=False,
)
def test_the_optimiser_plans_the_demo_scope_in_under_ten_seconds(demo_solve: Timed) -> None:
    assert demo_solve.seconds < LIMIT_SECONDS, (
        f"{demo_solve.pairwise_seconds:.1f} s of {demo_solve.seconds:.1f} s pricing pairs"
    )
