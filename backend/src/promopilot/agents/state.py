"""The agent graph's typed state (SPEC §9.6, ADR 0046) and what its Approval interrupt asks
and is answered with.

The state is checkpointed after every step, so it holds only values: the brief, the planning
request, the Planner's attempts of the planning round (ADR 0051), the plan revision chosen
from them with its plan facts, the Planner's notes (ADR 0049), the Critic's findings, the
explanations and the latest decision, with the Context agent's assumptions, open questions and
answered clarifications (ADR 0048), and every amendment (ADR 0052) and accepted relaxation
(ADR 0083). The diff from the
previous revision is on the plan revision (`plan.diff`), as is the simulation (ADR 0042). The
trace is not state: every step is a trace event stored as it happens (ADR 0047).
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
    Relaxation,
)
from promopilot.guardrails import PlanFacts


class DegradedReason(StrEnum):
    """Why a deterministic path ran instead of the LLM (SF-03): the default sequence instead of
    the planner agent (ADR 0049), or the fallback reading instead of the Context agent's LLM
    (ADR 0053)."""

    LLM_UNAVAILABLE = "llm_unavailable"
    """The LLM failed after its retries and fallback provider, and after one restart."""
    CASSETTE_MISSING = "cassette_missing"
    """Replay has no cassette for the request (`make record-cassettes`)."""
    NO_OPTIMISED_PLAN = "no_optimised_plan"
    """The planner stopped, or reached its step or tool-call limit, with no optimiser plan."""


class PlanAttempt(BaseModel):
    """One planner attempt in a planning round: a draft plan the Critic reviews. Only the best
    attempt becomes a plan revision (ADR 0051)."""

    model_config = ConfigDict(frozen=True)

    plan: PlanRevision
    facts: PlanFacts
    notes: tuple[str, ...] = ()
    competitor_response: tuple[str, ...] = ()
    degraded: DegradedReason | None = None
    findings: tuple[OpenIssue, ...] = ()
    """The Critic's violations and risk findings; empty until it has reviewed the attempt."""


class AcceptedRelaxation(BaseModel):
    """A relaxation the manager accepted (ADR 0052 D7), and the plan revision that offered it.
    Code applies its values to every later reading of the brief; the LLM never reads it
    (ADR 0083)."""

    model_config = ConfigDict(frozen=True)

    revision_number: int = Field(ge=1)
    relaxation: Relaxation


class PlanningState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    brief: str
    amendments: tuple[str, ...] = ()
    """Every amendment in the manager's words, oldest first; the Context agent reads them after
    the brief (ADR 0052). An accepted relaxation is in `accepted` instead."""
    accepted: tuple[AcceptedRelaxation, ...] = ()
    """Every accepted relaxation, oldest first, applied in code after each reading (ADR 0083)."""
    request: PlanningRequest | None = None
    assumptions: tuple[Assumption, ...] = ()
    """How the Context agent read the brief, from its latest reading (ADR 0048)."""
    questions: tuple[ClarificationQuestion, ...] = ()
    """What the Context agent asks before planning; the Clarify interrupt waits on them."""
    clarifications: tuple[Clarification, ...] = ()
    """Every question answered so far, oldest first."""
    context_degraded: DegradedReason | None = None
    """Why the latest reading of the brief was by rules; None when the LLM read it (ADR 0053)."""
    attempts: tuple[PlanAttempt, ...] = ()
    """The Planner's attempts in the current planning round, oldest first: the first and up to
    3 more, each after the Critic sent its findings back (ADR 0051). An amendment (#50) starts
    a new round."""
    plan: PlanRevision | None = None
    """The best attempt's plan, saved as the plan revision once the Critic hands it on. After
    an amendment it is the previous revision until the new round's is saved, which is diffed
    against it (ADR 0052)."""
    plan_request: PlanningRequest | None = None
    """The planning request `plan` was planned on, for the next revision's request changes."""
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
    competitor_response: tuple[str, ...] = ()
    """The planner notes that answer undercut KVIs, which the explanation keeps for the
    competitor panel (ADR 0068)."""
    planner_degraded: DegradedReason | None = None
    """Why the default sequence planned the latest plan; None when the planner agent did."""
    explanations: PlanExplanation | None = None
    """The Explainer's summary and rationales for the plan revision (ADR 0050)."""
    approval: PlanDecision | None = None
    """The latest decision on the plan revision; None until one is made, and again once the
    revision is amended."""


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


class AmendAnswer(BaseModel):
    """What else resumes the Approval interrupt: an amendment to the planning request, in the
    manager's words, which starts a new planning round (ADR 0052)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amendment: str
    relaxation: Relaxation | None = None
    """The relaxation this amendment accepts, whose text `amendment` is; code applies it and the
    Context agent's LLM never reads it (ADR 0083)."""


class ClarificationRequest(BaseModel):
    """What the Clarify interrupt waits on: answers to these questions (ADR 0048)."""

    model_config = ConfigDict(frozen=True)

    questions: tuple[ClarificationQuestion, ...]


class ClarificationAnswer(BaseModel):
    """What resumes the Clarify interrupt: an answer, in the manager's words, per question id."""

    model_config = ConfigDict(frozen=True)

    answers: dict[str, str]
