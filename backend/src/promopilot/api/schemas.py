"""Request/response schemas: the OpenAPI contract consumed by the frontend."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from promopilot.agents.tools.estimate_demand import ModelVersion
from promopilot.agents.tools.get_relations import Complement, Substitute
from promopilot.domain import PlanningRequest, PlanningSession, PlanRevision, SessionStatus
from promopilot.models.registry import ModelKind, RegisteredModel


class ModelEntry(BaseModel):
    """One registered model version; `live` marks the one the API is serving."""

    model_id: UUID
    kind: ModelKind
    version: int
    trained_at: datetime
    as_of_week: int
    metrics: dict[str, float]
    live: bool

    @classmethod
    def of(cls, entry: RegisteredModel, *, live: bool) -> "ModelEntry":
        return cls(
            model_id=entry.model_id,
            kind=entry.kind,
            version=entry.version,
            trained_at=entry.trained_at,
            as_of_week=entry.as_of_week,
            metrics=entry.metrics,
            live=live,
        )


class ModelList(BaseModel):
    """Registered models, newest first."""

    models: list[ModelEntry]


class RelationsResponse(BaseModel):
    """A SKU's substitutes (strongest first) and complements (highest lift first)."""

    model: ModelVersion
    sku_id: str
    substitutes: list[Substitute]
    complements: list[Complement]


class HealthChecks(BaseModel):
    database: Literal["ok", "error"]
    model_registry: Literal["ok", "missing"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: HealthChecks


BRIEF_MAX_CHARS = 2000


class CreateSessionRequest(BaseModel):
    brief: str = Field(max_length=BRIEF_MAX_CHARS, description="The brief, in plain English.")

    @field_validator("brief")
    @classmethod
    def _not_blank(cls, brief: str) -> str:
        if not brief.strip():
            raise ValueError("the brief is empty")
        return brief


class SessionCreated(BaseModel):
    session_id: UUID


class SessionResponse(BaseModel):
    """One planning session's read model: status, brief, planning request, latest revision."""

    session_id: UUID
    status: SessionStatus
    brief: str
    planning_request: PlanningRequest | None
    plan_revision: PlanRevision | None
    error: str | None

    @classmethod
    def of(cls, session: PlanningSession) -> "SessionResponse":
        return cls(
            session_id=session.id,
            status=session.status,
            brief=session.brief,
            planning_request=session.planning_request,
            plan_revision=session.latest_revision,
            error=session.error,
        )
