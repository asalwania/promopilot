"""Plan revisions: numbered versions of the promo plan within a planning session."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain.comparison import MechanismOutcome
from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import PolicyFinding
from promopilot.domain.selection import (
    BindingConstraint,
    ClearanceShortfall,
    NotSelectedOption,
    SolveStatus,
    WhyChosen,
)
from promopilot.domain.simulation import PlanSimulation


class PlanRevisionLine(BaseModel):
    """A plan line with the expected numbers the planning tool computed for it (rupees)."""

    model_config = ConfigDict(frozen=True)

    line: PlanLine
    expected_units: float = Field(ge=0)
    promo_cost: float = Field(ge=0)
    expected_incremental_profit: float
    why_chosen: WhyChosen | None = None
    """None only for revisions planned before the optimiser (E3)."""
    mechanism_comparison: tuple[MechanismOutcome, ...] = ()
    """Each mechanism's best option for the line's SKU and region, the line's own mechanism
    shown with the line itself (F-02, ADR 0041); empty for revisions planned before E7."""


class PlanRevision(BaseModel):
    """One numbered version of the promo plan within a planning session."""

    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=1)
    lines: tuple[PlanRevisionLine, ...] = ()
    solver_status: SolveStatus | None = None
    """None only for revisions planned before the optimiser (E3)."""
    objective: float | None = None
    """The plan's objective in rupees (ADR 0036)."""
    binding_constraints: tuple[BindingConstraint, ...] = ()
    not_selected: tuple[NotSelectedOption, ...] = ()
    """Up to five of the best options left out, one per SKU and region, best first."""
    simulation: PlanSimulation | None = None
    """The Monte Carlo simulation of the revision's plan (ADR 0042); None only for revisions
    planned before the simulator (E3-E6)."""
    clearance_shortfalls: tuple[ClearanceShortfall, ...] = ()
    """Clearance targets no plan could reach, and by how much this one misses them."""
    policy_findings: tuple[PolicyFinding, ...] = ()
    """Brief values that would have loosened company policy, which was kept instead."""

    @model_validator(mode="after")
    def _is_a_valid_promo_plan(self) -> Self:
        PromoPlan(lines=tuple(line.line for line in self.lines))
        return self
