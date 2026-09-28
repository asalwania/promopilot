"""The first eval metrics, on hand-built inputs (SPEC §12.2, ADR 0012, ADR 0056)."""

from promopilot.domain import (
    ClearanceShortfall,
    CompanyPolicy,
    PlanRevision,
    PlanRevisionLine,
    Region,
    SolveStatus,
    ViolationCode,
)
from promopilot.evals import (
    AsksClarification,
    DeclaresInfeasible,
    ExcludesRegion,
    MeetsClearance,
    PlanOutcome,
)
from promopilot.evals.metrics import (
    check_constraints,
    check_property,
    constraint_satisfaction,
    oracle_breach_rate,
    oracle_breaches,
)
from promopilot.evals.report import (
    Breach,
    ConstraintCheck,
    OracleScore,
    RunOutcome,
    RunResult,
)
from promopilot.guardrails import PlanFacts
from tests.unit.guardrails.test_validate_plan import fact, request

POLICY = CompanyPolicy()


# ---------------------------------------------------------------- constraint satisfaction


def test_a_plan_within_every_hard_constraint_on_its_own_numbers_passes() -> None:
    check, violations = check_constraints(
        SolveStatus.OPTIMAL, PlanFacts(lines=(fact(),)), request(), POLICY
    )

    assert (check, violations) == (ConstraintCheck.PASSED, ())


def test_a_plan_over_budget_on_its_own_numbers_fails() -> None:
    check, violations = check_constraints(
        SolveStatus.FEASIBLE,
        PlanFacts(lines=(fact(promo_cost=150_000.0),)),
        request(budget=100_000.0),
        POLICY,
    )

    assert check is ConstraintCheck.FAILED
    assert [violation.code for violation in violations] == [ViolationCode.BUDGET]


def test_an_infeasible_revision_is_not_scored() -> None:
    check, violations = check_constraints(
        SolveStatus.INFEASIBLE,
        PlanFacts(lines=(fact(promo_cost=150_000.0),)),
        request(budget=100_000.0),
        POLICY,
    )

    assert (check, violations) == (ConstraintCheck.INFEASIBLE, ())


def run(
    constraints: ConstraintCheck = ConstraintCheck.PASSED, breaches: tuple[Breach, ...] = ()
) -> RunResult:
    scored = constraints in (ConstraintCheck.PASSED, ConstraintCheck.FAILED)
    return RunResult(
        run=1,
        outcome=RunOutcome.PLANNED,
        constraints=constraints,
        oracle=OracleScore(
            incremental_profit=0.0,
            clearance_value=0.0,
            promo_cost=0.0,
            blended_margin=None,
            stock_capped_lines=0,
            breaches=breaches,
        )
        if scored
        else None,
    )


def test_constraint_satisfaction_is_the_share_of_scored_plans_that_pass_against_100_percent() -> (
    None
):
    runs = [
        run(),
        run(),
        run(ConstraintCheck.FAILED),
        run(ConstraintCheck.INFEASIBLE),
        run(ConstraintCheck.NO_PLAN),
    ]

    metric = constraint_satisfaction(runs)

    assert (metric.name, metric.count, metric.of) == ("constraint_satisfaction", 2, 3)
    assert metric.value == 2 / 3
    assert (metric.target, metric.direction, metric.passed) == (1.0, "at_least", False)
    assert metric.breakdown == {"failed": 1, "infeasible": 1, "no_plan": 1}


def test_constraint_satisfaction_passes_only_at_100_percent_and_is_unscored_with_no_plans() -> None:
    assert constraint_satisfaction([run(), run()]).passed is True
    empty = constraint_satisfaction([run(ConstraintCheck.NO_PLAN)])
    assert (empty.value, empty.passed, empty.of) == (None, None, 0)


# ---------------------------------------------------------------- the oracle breach rate


def outcome(
    promo_cost: float = 90_000.0, margin: float | None = 0.25, capped: int = 0
) -> PlanOutcome:
    return PlanOutcome(
        lines=(),
        incremental_profit=1_000.0,
        cannibalisation=0.0,
        halo=0.0,
        promo_cost=promo_cost,
        clearance_value=0.0,
        revenue=100_000.0,
        gross_profit=25_000.0,
        blended_margin=margin,
        stock_capped_lines=capped,
    )


def test_a_true_outcome_within_the_constraints_breaks_none() -> None:
    assert oracle_breaches(outcome(), request(budget=100_000.0, min_margin=0.20), POLICY) == ()


def test_each_constraint_the_true_outcome_breaks_is_a_breach() -> None:
    breaches = oracle_breaches(
        outcome(promo_cost=120_000.0, margin=0.15, capped=2),
        request(budget=100_000.0, min_margin=0.20),
        POLICY,
    )

    assert breaches == (
        Breach.PROMO_COST_OVER_BUDGET,
        Breach.MARGIN_BELOW_MINIMUM,
        Breach.DEMAND_OVER_STOCK,
    )


def test_with_no_minimum_margin_in_the_brief_the_true_margin_is_held_to_the_policy_floor() -> None:
    floor = POLICY.margin_floor
    below = oracle_breaches(outcome(margin=floor - 0.01), request(min_margin=None), POLICY)
    above = oracle_breaches(outcome(margin=floor + 0.01), request(min_margin=None), POLICY)

    assert (below, above) == ((Breach.MARGIN_BELOW_MINIMUM,), ())


def test_the_breach_rate_is_reported_with_no_target_and_counts_each_kind() -> None:
    runs = [
        run(breaches=(Breach.PROMO_COST_OVER_BUDGET, Breach.DEMAND_OVER_STOCK)),
        run(ConstraintCheck.FAILED, breaches=(Breach.DEMAND_OVER_STOCK,)),
        run(),
        run(ConstraintCheck.INFEASIBLE),
    ]

    metric = oracle_breach_rate(runs)

    assert (metric.name, metric.count, metric.of, metric.value) == (
        "oracle_breach_rate",
        2,
        3,
        2 / 3,
    )
    assert (metric.target, metric.passed) == (None, None)
    assert metric.breakdown == {
        "promo_cost_over_budget": 1,
        "margin_below_minimum": 0,
        "demand_over_stock": 2,
    }


def test_breaches_do_not_affect_constraint_satisfaction() -> None:
    runs = [run(breaches=(Breach.PROMO_COST_OVER_BUDGET,))]

    assert constraint_satisfaction(runs).value == 1.0


# ---------------------------------------------------------------- expected properties


def revision(
    status: SolveStatus = SolveStatus.OPTIMAL,
    regions: tuple[Region, ...] = (Region.NORTH,),
    shortfalls: tuple[ClearanceShortfall, ...] = (),
) -> PlanRevision:
    return PlanRevision(
        number=1,
        lines=tuple(
            PlanRevisionLine(
                line=fact(sku_id=f"S{i}", region=region).line,
                expected_units=100.0,
                promo_cost=1_000.0,
                expected_incremental_profit=500.0,
            )
            for i, region in enumerate(regions)
        ),
        solver_status=status,
        clearance_shortfalls=shortfalls,
    )


def test_asks_clarification_holds_when_that_field_was_asked_about() -> None:
    prop = AsksClarification(asks_clarification="marketing_budget")

    asked = check_property(prop, asked=("min_margin", "marketing_budget"), revision=None)
    not_asked = check_property(prop, asked=("min_margin",), revision=revision())

    assert (asked.property, asked.passed) == ("asks_clarification: marketing_budget", True)
    assert not not_asked.passed
    assert "min_margin" in not_asked.detail


def test_declares_infeasible_compares_the_final_revisions_status() -> None:
    infeasible = revision(SolveStatus.INFEASIBLE)
    expects = DeclaresInfeasible(declares_infeasible=True)
    expects_not = DeclaresInfeasible(declares_infeasible=False)

    assert check_property(expects, asked=(), revision=infeasible).passed
    assert not check_property(expects, asked=(), revision=revision()).passed
    assert check_property(expects_not, asked=(), revision=revision()).passed
    assert not check_property(expects, asked=(), revision=None).passed


def test_excludes_region_holds_when_no_final_plan_line_is_there() -> None:
    prop = ExcludesRegion(excludes_region=Region.WEST)

    assert check_property(prop, asked=(), revision=revision(regions=(Region.NORTH,))).passed
    failed = check_property(prop, asked=(), revision=revision(regions=(Region.WEST,)))
    assert not failed.passed
    assert "West" in failed.detail
    assert not check_property(prop, asked=(), revision=None).passed


def test_meets_clearance_holds_when_the_final_revision_has_no_shortfall_for_the_sku() -> None:
    prop = MeetsClearance(meets_clearance="S1")
    short = ClearanceShortfall(
        sku_id="S1",
        region=Region.NORTH,
        target=0.6,
        expected_sell_through=0.4,
        shortfall_units=20.0,
    )

    assert check_property(prop, asked=(), revision=revision()).passed
    assert not check_property(prop, asked=(), revision=revision(shortfalls=(short,))).passed
    assert not check_property(prop, asked=(), revision=None).passed
