"""The optimiser's latency budget on the demo brief (SPEC §6: optimiser under 10 s, ADR 0039).

The seed-42 world is fitted as `make train` fits it and the candidates are generated first;
only `solve` is timed, pairwise terms and CP-SAT together, with "why chosen" and the
not-selected list. The binding analysis is a separate post-step with its own time limit
(ADR 0038), so it is off for the budget and timed on its own. It runs twice and the faster
run counts, so one stall on a busy machine does not fail the test.
"""

import time

import pytest

from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    BindingEvidence,
    CompanyPolicy,
    ConstraintKind,
    PlanningRequest,
    PromoWindow,
    Region,
    Scope,
)
from promopilot.models import demand, relations
from promopilot.models.training import DEFAULT_SEED
from promopilot.optimizer import (
    FittedOptionFacts,
    OptionContext,
    SolverSettings,
    SolveStatus,
    generate_options,
    solve,
)
from tests.conftest import history_of

AS_OF = 104
BUDGET_SECONDS = 10.0
RUNS = 2

DEMO_BRIEF = PlanningRequest(
    as_of_week=AS_OF,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
    promo_window=PromoWindow(start_week=108, end_week=109),
    marketing_budget=200_000.0,
)
"""The demo brief's scope, Diwali window and ₹2 lakh budget (ADR 0036, ADR 0037)."""


@pytest.fixture(scope="module")
def demo_context(default_dataset: GeneratedDataset) -> OptionContext:
    history = history_of(default_dataset)
    model = demand.fit(history, AS_OF, DEFAULT_SEED)
    found = relations.fit(
        history, default_dataset.baskets, model, as_of_week=AS_OF, seed=DEFAULT_SEED
    )
    inventory = default_dataset.inventory
    policy = CompanyPolicy()
    return OptionContext(
        demand_model=model,
        relations=found,
        products=default_dataset.products,
        stock=pooled_stock(
            inventory[inventory["snapshot_week"] == AS_OF - 1], default_dataset.stores, policy
        ),
        policy=policy,
    )


@pytest.mark.model
def test_the_demo_brief_is_solved_within_the_optimiser_budget(
    demo_context: OptionContext,
) -> None:
    options = generate_options(DEMO_BRIEF, demo_context)
    facts = FittedOptionFacts(demo_context)

    timings = []
    results = []
    for _ in range(RUNS):
        started = time.perf_counter()
        results.append(
            solve(
                DEMO_BRIEF,
                options,
                facts,
                demo_context.policy,
                settings=SolverSettings(binding_time_limit_seconds=0),
                seed=0,
            )
        )
        timings.append(time.perf_counter() - started)

    result = results[0]
    assert result.status is SolveStatus.OPTIMAL
    assert result.pairs > 1_000  # the pairwise terms were priced, not skipped
    assert result.plan.lines
    assert len(result.why_chosen) == len(result.plan.lines)
    assert all(why.reasons for why in result.why_chosen)
    assert len(result.not_selected) <= 5
    assert min(timings) < BUDGET_SECONDS, f"solve took {', '.join(f'{t:.1f} s' for t in timings)}"


@pytest.mark.model
def test_the_binding_analysis_proves_the_demo_budget_binds_within_its_own_time_limit(
    demo_context: OptionContext,
) -> None:
    options = generate_options(DEMO_BRIEF, demo_context)
    facts = FittedOptionFacts(demo_context)
    policy = demo_context.policy
    settings = SolverSettings()
    plain = SolverSettings(binding_time_limit_seconds=0)

    started = time.perf_counter()
    solve(DEMO_BRIEF, options, facts, policy, settings=plain, seed=0)
    alone = time.perf_counter() - started
    started = time.perf_counter()
    result = solve(DEMO_BRIEF, options, facts, policy, settings=settings, seed=0)
    analysed = time.perf_counter() - started

    # The analysis may overrun its limit by one model build per re-solve.
    assert analysed - alone < settings.binding_time_limit_seconds + 3.0
    budget = [c for c in result.binding_constraints if c.kind is ConstraintKind.MARKETING_BUDGET]
    # The ₹2 lakh plan leaves worthwhile options out for want of money.
    assert [c.evidence for c in budget] in (
        [BindingEvidence.LOWER_BOUND],
        [BindingEvidence.EXACT],
    )
