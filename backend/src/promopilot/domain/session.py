"""Planning sessions: one conversation from brief to decision."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain.request import PlanningRequest
from promopilot.domain.revision import PlanRevision


class SessionStatus(StrEnum):
    """Every status a planning session can have (ADR 0046).

    planning -> awaiting_approval -> approved (final) or rejected (open for amendments); any
    failure while planning -> failed. awaiting_clarification arrives with the Context agent
    (#46).
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
