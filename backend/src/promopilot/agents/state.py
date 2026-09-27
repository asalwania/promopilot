"""The agent graph's typed state (SPEC §9.6, ADR 0046) and what its Approval interrupt asks
and is answered with.

The state is checkpointed after every step, so it holds only values: the brief, the planning
request, the plan revision with its plan facts, the Critic's findings, the planner's notes,
the explanations and the latest decision. Assumptions and clarifications (#46), the trace
(#45) and the diff from the previous revision (#50) join it with the tickets that produce
them; the simulation is on the plan revision (ADR 0042).
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import (
    DecisionKind,
    PlanDecision,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    Violation,
)
from promopilot.guardrails import PlanFacts


class PlanningState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    brief: str
    amendments: tuple[str, ...] = ()
    request: PlanningRequest | None = None
    plan: PlanRevision | None = None
    plan_facts: PlanFacts | None = None
    """The plan-time numbers the plan was chosen on, which the Critic validates."""
    critic_findings: tuple[Violation, ...] = ()
    iteration: int = 0
    """How many times the Planner has planned in this session."""
    planner_notes: tuple[str, ...] = ()
    """Deterministic sentences the Planner wants every summary to carry verbatim (#47), such as
    that the language model was unavailable; the Explainer puts them in the summary."""
    explanations: PlanExplanation | None = None
    """The Explainer's summary and rationales for the plan revision (ADR 0050)."""
    approval: PlanDecision | None = None
    """The latest decision on the plan revision; None until one is made."""


class ApprovalRequest(BaseModel):
    """What the Approval interrupt waits on: a decision on this plan revision."""

    model_config = ConfigDict(frozen=True)

    revision_number: int = Field(ge=1)


class ApprovalAnswer(BaseModel):
    """What resumes the Approval interrupt: approve, or reject with a reason."""

    model_config = ConfigDict(frozen=True)

    decision: DecisionKind
    revision_number: int = Field(ge=1)
    reason: str | None = None
