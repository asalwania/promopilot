"""Request/response schemas: the OpenAPI contract consumed by the frontend."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from promopilot.agents.tools.estimate_demand import ModelVersion
from promopilot.agents.tools.get_relations import Complement, Substitute
from promopilot.domain import (
    Amendment,
    Assumption,
    Clarification,
    ClarificationQuestion,
    CompetitorReaction,
    PlanDecision,
    PlanningRequest,
    PlanningSession,
    PlanRevision,
    PlanSimulation,
    SessionStatus,
    SessionUsage,
)
from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.simulator import MAX_RUNS, MIN_RUNS


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
    decisions: list[PlanDecision] = Field(
        description="Every approval and rejection, oldest first: the session's audit trail."
    )
    usage: SessionUsage = Field(
        description="What the session's LLM calls used and cost: the sums of its token-usage "
        "trace events (ADR 0047)."
    )
    assumptions: list[Assumption] = Field(
        description="How the Context agent read the brief, each with its source and confidence "
        "(ADR 0048)."
    )
    questions: list[ClarificationQuestion] = Field(
        description="The clarification questions waiting for an answer (awaiting_clarification)."
    )
    clarifications: list[Clarification] = Field(
        description="Every question answered so far, oldest first."
    )
    amendments: list[Amendment] = Field(
        description="Every amendment to the planning request, oldest first (ADR 0052)."
    )

    @classmethod
    def of(cls, session: PlanningSession) -> "SessionResponse":
        return cls(
            session_id=session.id,
            status=session.status,
            brief=session.brief,
            planning_request=session.planning_request,
            plan_revision=session.latest_revision,
            error=session.error,
            decisions=list(session.decisions),
            usage=session.usage,
            assumptions=list(session.assumptions),
            questions=list(session.questions),
            clarifications=list(session.clarifications),
            amendments=list(session.amendments),
        )


class TraceStreamEnd(BaseModel):
    """The last event of a session's trace stream (`event: end`): the session is final, so no
    more trace events can come (ADR 0047)."""

    session_id: UUID
    status: SessionStatus


class ApproveRequest(BaseModel):
    """Approve a plan revision: it must be the session's latest (ADR 0046)."""

    model_config = ConfigDict(extra="forbid")

    revision_number: int = Field(ge=1, description="The plan revision being approved.")


REASON_MAX_CHARS = 2000


class RejectRequest(BaseModel):
    """Reject a plan revision, the session's latest, with the reason (ADR 0046)."""

    model_config = ConfigDict(extra="forbid")

    revision_number: int = Field(ge=1, description="The plan revision being rejected.")
    reason: str = Field(max_length=REASON_MAX_CHARS, description="Why, in plain English.")

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError("a rejection needs a reason")
        return reason


ANSWER_MAX_CHARS = 2000


class ClarifyRequest(BaseModel):
    """Answers to the session's open clarification questions (ADR 0048)."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str] = Field(
        min_length=1,
        description="An answer in plain English for every open question, keyed by its id.",
    )

    @field_validator("answers")
    @classmethod
    def _answered(cls, answers: dict[str, str]) -> dict[str, str]:
        for question_id, answer in answers.items():
            if not answer.strip():
                raise ValueError(f"the answer to {question_id} is empty")
            if len(answer) > ANSWER_MAX_CHARS:
                raise ValueError(
                    f"the answer to {question_id} is longer than {ANSWER_MAX_CHARS} characters"
                )
        return answers


AMENDMENT_MAX_CHARS = 2000


class AmendRequest(BaseModel):
    """Amend the planning request of a session awaiting approval or rejected (ADR 0052): in
    plain English, or by accepting the latest revision's relaxation. Exactly one of the two."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None,
        max_length=AMENDMENT_MAX_CHARS,
        description='The change, in plain English ("cut budget to ₹6 lakh", "drop West").',
    )
    accept_relaxation: bool = Field(
        default=False,
        description="Accept the latest plan revision's smallest relaxation (ADR 0044) as the "
        "amendment instead of writing one.",
    )

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str | None) -> str | None:
        if text is not None and not text.strip():
            raise ValueError("an amendment needs text")
        return text

    @model_validator(mode="after")
    def _text_or_relaxation(self) -> Self:
        if (self.text is None) == (not self.accept_relaxation):
            raise ValueError("give either the amendment's text or accept_relaxation: true")
        return self


class SimulatePlanRequest(BaseModel):
    """Re-simulate a session's latest plan revision (ADR 0043), optionally against a
    competitor reaction (ADR 0045). The seed is configuration."""

    model_config = ConfigDict(extra="forbid")

    n_runs: int | None = Field(
        default=None,
        ge=MIN_RUNS,
        le=MAX_RUNS,
        description="Runs to simulate; omit for the configured default (SIMULATION_RUNS).",
    )
    competitor_reaction: CompetitorReaction | None = Field(
        default=None,
        description="The competitor-reaction scenario; omit or null for a competitor that "
        "never reacts.",
    )


class PlanSimulationResponse(BaseModel):
    """A plan revision's new simulation, now stored against it in place of the old one."""

    session_id: UUID
    revision_number: int
    demand_model: ModelVersion
    """The demand model simulated: the latest one (ADR 0043)."""
    as_of_week: int
    """The week whose inventory snapshot caps the units: the planning request's."""
    simulation: PlanSimulation
