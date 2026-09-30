"""How far a plan keeps its expected numbers from its limits (ADR 0080)."""

from pydantic import BaseModel, ConfigDict, Field

P90_Z = 1.2816
"""The standard normal's 90th percentile: P90 units are mean + P90_Z x std (ADR 0035)."""


class SafetyMargin(BaseModel):
    """The quantiles a plan is kept within its limits at (ADR 0080). The defaults plan on
    expected values, as before: the budget at the expected promo cost, stock at P90 units and
    the margin at the expected blended margin.

    - `budget_quantile`: each plan line's promo cost counts at this quantile against the
      marketing budget and the regional caps (0.9: its P90).
    - `stock_sigmas`: each line's expected units plus this many standard deviations must fit
      its available stock; never below P90_Z, the P90 rule option generation prunes on.
    - `margin_quantile`: the blended margin must reach the minimum with each line's units at
      this quantile, whichever side lowers the blend (0.1: its P10).
    """

    model_config = ConfigDict(frozen=True)

    budget_quantile: float = Field(default=0.5, ge=0.5, lt=1)
    stock_sigmas: float = Field(default=P90_Z, ge=P90_Z)
    margin_quantile: float = Field(default=0.5, gt=0, le=0.5)


class PlanSafetyMargin(SafetyMargin):
    """The safety margin a plan revision was planned with, and its promo cost as budgeted."""

    planned_promo_cost: float = Field(ge=0)
    """The plan's promo cost at the budget quantile: what the budget constraint counted."""
    budget_margin_waived: bool = False
    """The budget was planned at the expected promo cost because the brief's clearance
    targets need the whole budget: with the margin, no plan reaches them (ADR 0080)."""
