"""Planning sessions: one conversation from brief to decision."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from promopilot.domain.plan import PlanRevision
from promopilot.domain.request import PlanningRequest


class SessionStatus(StrEnum):
    """Every status a planning session can have. E3 uses planning, awaiting_approval, failed."""

    PLANNING = "planning"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class PlanningSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    brief: str
    status: SessionStatus
    planning_request: PlanningRequest | None = None
    latest_revision: PlanRevision | None = None
    error: str | None = None
    """Why the session failed, in words a promotions manager can act on."""
