"""The agent graph's typed state (SPEC §9.6, ADR 0046) and what its Approval interrupt asks
and is answered with.

The state is checkpointed after every step, so it holds only values: the brief, the planning
request, the Planner's attempts of the planning round (ADR 0051), the plan revision chosen
from them with its plan facts, the Planner's notes (ADR 0049), the Critic's findings, the
explanations and the latest decision, with the Context agent's assumptions, open questions and
answered clarifications (ADR 0048). The diff from the previous revision (#50) joins it with the
ticket that produces it; the simulation is on the plan revision (ADR 0042). The trace is not
state: every step is a trace event stored as it happens (ADR 0047).
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import (
    Assumption,
    Clarification,
    ClarificationQuestion,
    DecisionKind,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
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


class PlanAttempt(BaseModel):
    """One planner attempt in a planning round: a draft plan the Critic reviews. Only the best
    attempt becomes a plan revision (ADR 0051)."""

    model_config = ConfigDict(frozen=True)

    plan: PlanRevision
    facts: PlanFacts
    notes: tuple[str, ...] = ()
    degraded: DegradedReason | None = None
    findings: tuple[OpenIssue, ...] = ()
    """The Critic's violations and risk findings; empty until it has reviewed the attempt."""


class PlanningState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    brief: str
    amendments: tuple[str, ...] = ()
    request: PlanningRequest | None = None
    assumptions: tuple[Assumption, ...] = ()
    """How the Context agent read the brief, from its latest reading (ADR 0048)."""
    questions: tuple[ClarificationQuestion, ...] = ()
    """What the Context agent asks before planning; the Clarify interrupt waits on them."""
    clarifications: tuple[Clarification, ...] = ()
    """Every question answered so far, oldest first."""
    attempts: tuple[PlanAttempt, ...] = ()
    """The Planner's attempts in the current planning round, oldest first: the first and up to
    3 more, each after the Critic sent its findings back (ADR 0051). An amendment (#50) starts
    a new round."""
    plan: PlanRevision | None = None
    """The best attempt's plan, saved as the plan revision once the Critic hands it on."""
    plan_facts: PlanFacts | None = None
    """The plan-time numbers the plan was chosen on, which the Critic validates."""
    critic_findings: tuple[OpenIssue, ...] = ()
    """The latest attempt's findings while the Critic loops, then the chosen plan's open
    issues."""
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


class ClarificationRequest(BaseModel):
    """What the Clarify interrupt waits on: answers to these questions (ADR 0048)."""

    model_config = ConfigDict(frozen=True)

    questions: tuple[ClarificationQuestion, ...]


class ClarificationAnswer(BaseModel):
    """What resumes the Clarify interrupt: an answer, in the manager's words, per question id."""

    model_config = ConfigDict(frozen=True)

    answers: dict[str, str]
