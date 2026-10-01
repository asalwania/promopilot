"""A plan revision's totals and the budget left, computed deterministically so that the
Explainer only has to cite them (#185, ADR 0090).

The Explainer's LLM never computes numbers (SPEC §13.4), yet left to itself it adds up the
plan lines' amounts or subtracts the spend from the budget, and cites a figure no tool output
shows. Each total here adds the amounts as a line shows them (whole rupees, whole units), so
it is the figure anyone adding up the lines reaches too, within half a rupee or unit per line
of the exact sum.
"""

from pydantic import BaseModel, ConfigDict

from promopilot.domain import PlanRevision


class PlanTotals(BaseModel):
    """Whole rupees and whole units."""

    model_config = ConfigDict(frozen=True)

    expected_units: int
    promo_cost: int
    expected_incremental_profit: int
    budget_left_at_expected_promo_cost: int
    """The marketing budget less `promo_cost`."""
    budget_left_at_planned_promo_cost: int | None
    """The marketing budget less the plan's promo cost at its safety-margin quantile, which the
    budget constraint counted (ADR 0080); None for a revision with no safety margin."""
    clearance_shortfall_units: int


def plan_totals(revision: PlanRevision, marketing_budget: float) -> PlanTotals:
    """The totals of `revision`'s lines and what is left of `marketing_budget`."""
    promo_cost = sum(round(planned.promo_cost) for planned in revision.lines)
    margin = revision.safety_margin
    return PlanTotals(
        expected_units=sum(round(planned.expected_units) for planned in revision.lines),
        promo_cost=promo_cost,
        expected_incremental_profit=sum(
            round(planned.expected_incremental_profit) for planned in revision.lines
        ),
        budget_left_at_expected_promo_cost=round(marketing_budget) - promo_cost,
        budget_left_at_planned_promo_cost=None
        if margin is None
        else round(marketing_budget) - round(margin.planned_promo_cost),
        clearance_shortfall_units=sum(
            round(shortfall.shortfall_units) for shortfall in revision.clearance_shortfalls
        ),
    )
