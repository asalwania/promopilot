"""Planning sessions: one conversation from brief to decision."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain.assumption import Assumption, Clarification, ClarificationQuestion
from promopilot.domain.request import PlanningRequest
from promopilot.domain.revision import PlanRevision
from promopilot.domain.selection import Relaxation
from promopilot.domain.trace import SessionUsage


class SessionStatus(StrEnum):
    """Every status a planning session can have (ADR 0046).

    planning -> awaiting_approval -> approved (final) or rejected (open for amendments); any
    failure while planning -> failed; planning -> awaiting_clarification -> planning when the
    questions are answered (ADR 0048); awaiting_approval or rejected -> planning when the
    request is amended (ADR 0052).
    """

    PLANNING = "planning"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class DecisionKind(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class PlanDecision(BaseModel):
    """One human decision on one plan revision: an approval or a rejection with its reason.
    Every decision is kept, in order, as the session's audit trail (SF-04, ADR 0046)."""

    model_config = ConfigDict(frozen=True)

    decision: DecisionKind
    revision_number: int = Field(ge=1)
    reason: str | None = None
    """Why the revision was rejected; None for an approval."""
    decided_at: datetime


class Amendment(BaseModel):
    """A change to the planning request, in the manager's words, made while a plan revision
    waited for a decision (AG-05, ADR 0052). Every amendment is kept, oldest first."""

    model_config = ConfigDict(frozen=True)

    text: str
    amends_revision: int = Field(ge=1)
    """The plan revision that was the session's latest when it was amended."""
    relaxation: Relaxation | None = None
    """The relaxation the manager accepted (ADR 0044), when the amendment accepts one; its
    text is then written from it."""
    amended_at: datetime


class PlanningSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    brief: str
    status: SessionStatus
    planning_request: PlanningRequest | None = None
    latest_revision: PlanRevision | None = None
    error: str | None = None
    """Why the session failed, in words a promotions manager can act on."""
    thread_id: str | None = None
    """The agent graph's checkpoint thread (ADR 0046); None for sessions planned before E8."""
    decisions: tuple[PlanDecision, ...] = ()
    """Every approval and rejection, oldest first."""
    usage: SessionUsage = SessionUsage()
    """What its LLM calls used and cost: the sums of its token-usage trace events (ADR 0047)."""
    assumptions: tuple[Assumption, ...] = ()
    """How the Context agent read the brief, from its latest reading (ADR 0048)."""
    questions: tuple[ClarificationQuestion, ...] = ()
    """The clarification questions waiting for an answer; empty unless awaiting one."""
    clarifications: tuple[Clarification, ...] = ()
    """Every question answered so far, oldest first."""
    amendments: tuple[Amendment, ...] = ()
    """Every amendment, oldest first (ADR 0052)."""
