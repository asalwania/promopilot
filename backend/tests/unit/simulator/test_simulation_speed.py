"""The simulator's latency budget (SPEC §6, F-09 AC3, E7 exit): a 100-line plan at 1,000 runs
in under 10 s, on the fitted seed-42 world (ADR 0042).

The plan promotes the first 100 SKU-regions of the demo brief's categories in all four regions,
cycling through three mechanisms and every duration, so 4-week lines are as common as 1-week
ones. The simulation runs twice and the faster run counts, so one stall on a busy machine does
not fail the test (ADR 0039).
"""

import itertools
import time

import pytest

from promopilot.domain import Mechanism, PlanLine, PromoPlan, Region, TargetSegment
from promopilot.models.demand import DemandModel
from promopilot.optimizer import OptionContext
from promopilot.simulator import DEFAULT_RUNS, SimulationInputs, simulate
from tests.conftest import DEMO_BRIEF

BUDGET_SECONDS = 10.0
LINES = 100
RUNS = 2
MECHANISMS = [(Mechanism.PCT_OFF, 10), (Mechanism.FIXED_PRICE, 15), (Mechanism.BOGO, 50)]


def hundred_lines(context: OptionContext) -> tuple[PlanLine, ...]:
    products = context.products
    skus = sorted(products.loc[products["category"].isin(DEMO_BRIEF.scope.categories), "sku_id"])
    pairs = itertools.islice(itertools.product(skus, Region), LINES)
    return tuple(
        PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=MECHANISMS[n % len(MECHANISMS)][0],
            depth_pct=MECHANISMS[n % len(MECHANISMS)][1],
            duration_weeks=n % 4 + 1,
            start_week=DEMO_BRIEF.promo_window.start_week,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        )
        for n, (sku_id, region) in enumerate(pairs)
    )


@pytest.mark.model
def test_a_100_line_plan_simulates_1000_runs_within_the_budget(
    demo_context: OptionContext,
) -> None:
    plan = PromoPlan(lines=hundred_lines(demo_context))
    model = demo_context.demand_model
    assert isinstance(model, DemandModel)
    inputs = SimulationInputs(demand=model, stock=demo_context.stock, policy=demo_context.policy)
    assert len(plan.lines) == LINES

    timings = []
    results = []
    for _ in range(RUNS):
        started = time.perf_counter()
        results.append(simulate(plan, inputs, n_runs=DEFAULT_RUNS, seed=0))
        timings.append(time.perf_counter() - started)

    assert results[0] == results[1]
    assert len(results[0].lines) == LINES
    took = ", ".join(f"{t:.1f} s" for t in timings)
    assert min(timings) < BUDGET_SECONDS, f"simulate took {took}"
