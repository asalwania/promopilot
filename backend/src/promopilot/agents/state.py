"""The agent graph's typed state (SPEC §9.6, ADR 0046) and what its Approval interrupt asks
and is answered with.

The state is checkpointed after every step, so it holds only values: the brief, the planning
request, the plan revision with its plan facts, the Planner's notes (ADR 0049), the Critic's
findings, the explanations and the latest decision. Assumptions and clarifications (#46), the
trace (#45) and the diff from the previous revision (#50) join it with the tickets that
produce them; the simulation is on the plan revision (ADR 0042).
"""

from enum import StrEnum
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


class DegradedReason(StrEnum):
    """Why the deterministic default sequence planned instead of the planner agent (SF-03,
    ADR 0049)."""

    LLM_UNAVAILABLE = "llm_unavailable"
    """The LLM failed after its retries and fallback provider, and after one restart."""
    CASSETTE_MISSING = "cassette_missing"
    """Replay has no cassette for the planner's request (`make record-cassettes`)."""
    NO_OPTIMISED_PLAN = "no_optimised_plan"
    """The planner stopped, or reached its step or tool-call limit, with no optimiser plan."""


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
    """The Planner's explanation of the plan it chose, which the Explainer puts in every summary
    verbatim: why the default sequence planned it, and how it answers undercut KVIs (ADR 0049).
    Written from tool outputs only."""
    planner_degraded: DegradedReason | None = None
    """Why the default sequence planned the latest plan; None when the planner agent did."""
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
