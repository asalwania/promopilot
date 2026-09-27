"""The template Explainer (ADR 0046): explanations from the plan revision's own numbers."""

from hypothesis import given, settings
from hypothesis import strategies as st

from promopilot.agents import template_explanations
from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ConstraintKind,
    ConstraintSource,
    Mechanism,
    PlanLine,
    PlanRevision,
    PlanRevisionLine,
    Region,
    Relaxation,
    RelaxedConstraint,
    SolveStatus,
    TargetSegment,
    Violation,
    ViolationCode,
)
from promopilot.guardrails import check_numeric_grounding

money = st.floats(min_value=-2_000_000, max_value=2_000_000, allow_nan=False)


def revision(units: float, cost: float, profit: float, objective: float) -> PlanRevision:
    bundle = PlanLine(
        sku_id="SKU0012",
        region=Region.WEST,
        mechanism=Mechanism.BUNDLE,
        depth_pct=15,
        duration_weeks=1,
        start_week=60,
        target_segment=TargetSegment.FAMILIES,
        bundle_partner_sku_id="SKU0031",
    )
    single = PlanLine(
        sku_id="SKU0029",
        region=Region.NORTH,
        mechanism=Mechanism.PCT_OFF,
        depth_pct=25,
        duration_weeks=3,
        start_week=58,
        target_segment=TargetSegment.ALL_CUSTOMERS,
    )
    return PlanRevision(
        number=12,
        lines=(
            PlanRevisionLine(
                line=bundle,
                expected_units=units,
                promo_cost=abs(cost),
                expected_incremental_profit=profit,
            ),
            PlanRevisionLine(
                line=single,
                expected_units=units / 3,
                promo_cost=abs(cost) / 7,
                expected_incremental_profit=-profit / 11,
            ),
        ),
        solver_status=SolveStatus.INFEASIBLE,
        objective=objective,
        binding_constraints=(
            BindingConstraint(
                kind=ConstraintKind.CLEARANCE_TARGET,
                source=ConstraintSource.BRIEF,
                limit=0.9,
                sku_id="SKU0029",
                region=Region.NORTH,
                evidence=BindingEvidence.INFEASIBLE,
                objective_gain=None,
            ),
        ),
        relaxation=Relaxation(
            changes=(
                RelaxedConstraint(
                    kind=ConstraintKind.CLEARANCE_TARGET,
                    sku_id="SKU0029",
                    current=0.9,
                    relaxed=0.7027,
                    change=0.219,
                ),
            ),
            policy_binds=True,
            proven=True,
        ),
    )


def test_each_plan_line_gets_a_rationale_and_the_summary_names_what_binds() -> None:
    planned = revision(412.4, 18_250.0, 61_874.6, 172_384.2)
    issue = Violation(code=ViolationCode.CLEARANCE_TARGET, message="short")

    explanations = template_explanations(planned, (issue,))

    first, second = explanations.lines
    assert first.startswith("SKU0012 in West: bundle with SKU0031 at 15% for 1 week from W60")
    assert "412 units" in first
    assert "₹18,250" in first
    assert "₹61,875" in first
    assert second.startswith("SKU0029 in North: % off at 25% for 3 weeks from W58")
    assert "-₹5,625" in second
    summary = explanations.summary
    assert "Infeasible" in summary
    assert "₹1,72,384" in summary
    assert "clearance target" in summary
    assert "Company policy binds" in summary
    assert "CLEARANCE_TARGET" in summary


def test_an_empty_plan_says_nothing_paid_for_itself() -> None:
    empty = PlanRevision(number=1, solver_status=SolveStatus.OPTIMAL, objective=0.0)

    explanations = template_explanations(empty)

    assert explanations.lines == ()
    assert "No promo option pays for itself" in explanations.summary


@settings(max_examples=200, deadline=None)
@given(
    units=st.floats(min_value=0, max_value=5_000_000, allow_nan=False),
    cost=money,
    profit=money,
    objective=money,
)
def test_template_explanations_always_pass_numeric_grounding(
    units: float, cost: float, profit: float, objective: float
) -> None:
    planned = revision(units, cost, profit, objective)

    explanations = template_explanations(planned)

    for text in (explanations.summary, *explanations.lines):
        report = check_numeric_grounding(text, [planned])
        assert report.ungrounded == (), text
