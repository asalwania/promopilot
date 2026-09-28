"""A plan does not depend on how fast or busy the machine is (ADR 0055).

Every optimiser phase (the closest plan, the main solve, the binding analysis, the relaxation)
stops on CP-SAT's deterministic time, a count of work done, and the wall-clock limits are only
safety nets. So wherever a work budget runs out, the same input ends in the same place on any
machine, and recorded sessions replay (ADR 0054). Checked on the seed-42 demo world, fitted as
`make train` fits it (marker `model`).
"""

from dataclasses import replace

import pytest

from promopilot.optimizer import (
    FittedOptionFacts,
    OptimisationResult,
    OptionContext,
    SolverSettings,
    SolveStatus,
    generate_options,
    solve,
)
from tests.conftest import DEMO_BRIEF
from tests.unit.optimizer.test_demo_brief_speed import CONSTRAINED

GENEROUS = 10.0
"""How much longer every wall-clock net is in the second run."""


def nets_times(settings: SolverSettings, factor: float) -> SolverSettings:
    return replace(
        settings,
        time_limit_seconds=settings.time_limit_seconds * factor,
        binding_time_limit_seconds=settings.binding_time_limit_seconds * factor,
        relaxation_time_limit_seconds=settings.relaxation_time_limit_seconds * factor,
    )


@pytest.mark.model
def test_a_work_budget_that_runs_out_ends_the_demo_search_in_the_same_place(
    demo_context: OptionContext,
) -> None:
    # The constrained demo brief has a clearance target, so it runs the closest-plan phase,
    # then the main solve, then the binding analysis, each on a budget too small to finish.
    options = generate_options(CONSTRAINED, demo_context)
    facts = FittedOptionFacts(demo_context)
    tight = SolverSettings(deterministic_limit=0.5, binding_deterministic_limit=0.5)

    def solved(settings: SolverSettings) -> OptimisationResult:
        return solve(CONSTRAINED, options, facts, demo_context.policy, settings=settings, seed=0)

    first = solved(tight)
    second = solved(nets_times(tight, GENEROUS))

    assert first.status is SolveStatus.FEASIBLE, "the budget ran out before optimality"
    assert first == second


@pytest.mark.model
def test_the_binding_analysis_is_the_same_whatever_the_wall_clock_nets(
    demo_context: OptionContext,
) -> None:
    options = generate_options(DEMO_BRIEF, demo_context)
    facts = FittedOptionFacts(demo_context)

    def solved(settings: SolverSettings) -> OptimisationResult:
        return solve(DEMO_BRIEF, options, facts, demo_context.policy, settings=settings, seed=0)

    first = solved(SolverSettings())
    second = solved(nets_times(SolverSettings(), GENEROUS))

    assert first.status is SolveStatus.OPTIMAL
    assert first.binding_constraints
    assert first == second
