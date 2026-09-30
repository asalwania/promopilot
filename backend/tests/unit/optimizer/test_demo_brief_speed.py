"""The optimiser's latency budget on the demo brief (SPEC §6: optimiser under 10 s, ADR 0039).

The seed-42 world is fitted as `make train` fits it and the candidates are generated first;
only `solve` is timed, pairwise terms and CP-SAT together, with "why chosen" and the
not-selected list. The binding analysis is a separate post-step with its own time limit
(ADR 0038), so it is off for the budget and timed on its own. It runs twice and the faster
run counts, so one stall on a busy machine does not fail the test.
"""

import time

import pytest

from promopilot.domain import BindingEvidence, ConstraintKind, PlanningRequest
from promopilot.guardrails import (
    ViolationCode,
    validate_plan,
)
from promopilot.optimizer import (
    FittedOptionFacts,
    OptionContext,
    SolverSettings,
    SolveStatus,
    generate_options,
    plan_facts,
    solve,
)
from tests.conftest import DEMO_BRIEF

BUDGET_SECONDS = 10.0
RUNS = 2
SOLVED = (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
"""Under CPU contention CP-SAT can reach its time limit before proving optimality and return
a valid FEASIBLE plan; these tests time the solve, so either status is accepted."""


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
    assert result.status in SOLVED
    assert result.objective > 0
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


CONSTRAINED = PlanningRequest.model_validate(
    DEMO_BRIEF.model_dump()
    | {
        "clearance_targets": [{"sku_id": "SKU0029", "sell_through": 0.5}],
        "regional_budget_caps": {"North": 90_000.0},
        "kvi_price_tolerance": 0.02,
    }
)
"""The demo brief with the brief's optional constraints (ADR 0040): SKU0029 is overstocked in
both regions, and three North KVIs are undercut."""


@pytest.mark.model
def test_the_demo_brief_with_its_optional_constraints_keeps_them_within_the_budget(
    demo_context: OptionContext,
) -> None:
    options = generate_options(CONSTRAINED, demo_context)
    facts = FittedOptionFacts(demo_context)
    plain = SolverSettings(binding_time_limit_seconds=0)

    timings = []
    results = []
    for _ in range(RUNS):
        started = time.perf_counter()
        results.append(
            solve(CONSTRAINED, options, facts, demo_context.policy, settings=plain, seed=0)
        )
        timings.append(time.perf_counter() - started)

    result = results[0]
    assert result.status in SOLVED
    assert result.plan.lines
    assert result.objective > 0
    assert options.price_matches
    plan = plan_facts(options, list(result.selected), facts, result.safety_margin)
    violations = validate_plan(plan, CONSTRAINED, demo_context.policy)
    # Every constraint holds but a clearance target no plan reaches, and that is reported.
    assert {(v.code, v.sku_id, v.region) for v in violations} == {
        (ViolationCode.CLEARANCE_TARGET, s.sku_id, s.region) for s in result.clearance_shortfalls
    }
    assert min(timings) < BUDGET_SECONDS, f"solve took {', '.join(f'{t:.1f} s' for t in timings)}"
