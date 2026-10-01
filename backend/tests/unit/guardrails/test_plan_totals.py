"""A plan's totals and the budget left, computed so the Explainer's LLM never adds up the lines
or subtracts the spend from the budget itself (#185, ADR 0090)."""

from promopilot.domain import (
    Mechanism,
    PlanLine,
    PlanRevision,
    PlanRevisionLine,
    Region,
    TargetSegment,
)
from promopilot.guardrails import plan_totals


def line(sku: str, units: float, cost: float, profit: float) -> PlanRevisionLine:
    return PlanRevisionLine(
        line=PlanLine(
            sku_id=sku,
            region=Region.NORTH,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=10,
            duration_weeks=1,
            start_week=54,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        ),
        expected_units=units,
        promo_cost=cost,
        expected_incremental_profit=profit,
    )


def test_each_total_adds_the_amounts_as_the_lines_show_them() -> None:
    revision = PlanRevision(
        number=1, lines=(line("SKU0001", 0.4, 1.4, 2.4), line("SKU0002", 0.4, 1.4, 2.4))
    )

    totals = plan_totals(revision, marketing_budget=10.0)

    assert (totals.expected_units, totals.promo_cost, totals.expected_incremental_profit) == (
        0,
        2,
        4,
    )
    assert totals.budget_left_at_expected_promo_cost == 8
    assert totals.budget_left_at_planned_promo_cost is None
    assert totals.clearance_shortfall_units == 0
