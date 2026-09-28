"""Plan revisions: numbered versions of the promo plan within a planning session."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain.comparison import MechanismOutcome
from promopilot.domain.explanation import PlanExplanation
from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import PolicyFinding
from promopilot.domain.risk import OpenIssue
from promopilot.domain.selection import (
    BindingConstraint,
    ClearanceShortfall,
    NotSelectedOption,
    Relaxation,
    SolveStatus,
    WhyChosen,
)
from promopilot.domain.simulation import PlanSimulation
from promopilot.domain.vocabulary import Region


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


class LineChange(BaseModel):
    """A plan line whose SKU and region are in both revisions but whose decision changed."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    region: Region
    fields: tuple[str, ...]
    """The plan-line fields that changed (mechanism, depth_pct, ...), in `PlanLine` order."""
    before: PlanRevisionLine
    after: PlanRevisionLine


class RequestChange(BaseModel):
    """A planning-request field an amendment changed, shown as the explanation may cite it."""

    model_config = ConfigDict(frozen=True)

    field: str
    before: str
    after: str


class RevisionDiff(BaseModel):
    """What changed from the previous plan revision (AG-05, ADR 0052): plan lines matched by
    (SKU, region), the objective and promo-cost deltas, and the planning-request changes."""

    model_config = ConfigDict(frozen=True)

    from_revision: int = Field(ge=1)
    added: tuple[PlanRevisionLine, ...] = ()
    removed: tuple[PlanRevisionLine, ...] = ()
    changed: tuple[LineChange, ...] = ()
    unchanged: int = Field(default=0, ge=0)
    """Lines with the same decision in both revisions, whatever their expected numbers."""
    objective_before: float | None = None
    objective_after: float | None = None
    objective_delta: float | None = None
    """None unless both revisions have an objective."""
    promo_cost_before: float = 0.0
    promo_cost_after: float = 0.0
    promo_cost_delta: float = 0.0
    request_changes: tuple[RequestChange, ...] = ()


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
    relaxation: Relaxation | None = None
    """For a request that is infeasible, or not proven feasible in time, the smallest change
    to the brief's constraints that makes it feasible (ADR 0044); None otherwise."""
    open_issues: tuple[OpenIssue, ...] = ()
    """Violations and risk findings the Critic found that the revision still has when it goes
    for approval (ADR 0046, ADR 0051); empty for revisions planned before E8."""
    explanation: PlanExplanation | None = None
    """The Explainer's summary and rationales (ADR 0050); None until the Explainer has run,
    and for revisions planned before #49."""
    diff: RevisionDiff | None = None
    """What changed from the previous plan revision (ADR 0052); None for the first."""

    @model_validator(mode="after")
    def _is_a_valid_promo_plan(self) -> Self:
        PromoPlan(lines=tuple(line.line for line in self.lines))
        return self

    @model_validator(mode="after")
    def _one_rationale_per_line(self) -> Self:
        explained = self.explanation
        if explained is not None and len(explained.rationales) != len(self.lines):
            raise ValueError("an explanation has one rationale per plan line")
        return self
