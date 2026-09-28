"""Assumptions and clarifications: how the Context agent read a brief (AG-01, AG-02, ADR 0048)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AssumptionSource(StrEnum):
    """Where an assumed value came from."""

    BRIEF = "brief"
    DATA = "data"
    DEFAULT = "default"


class Assumption(BaseModel):
    """One planning-request field (or a fact the plan relies on) as the agent read or inferred
    it: its value in words, where it came from and how sure the agent is (ADR 0048)."""

    model_config = ConfigDict(frozen=True)

    field: str
    """The planning-request field, e.g. marketing_budget or scope.regions; or objective,
    target_segment, as_of_week, overstocked_skus, undercut_kvis."""
    value: str
    """The value as the manager should read it, e.g. "North, West"."""
    source: AssumptionSource
    confidence: float = Field(ge=0, le=1)
    """From 0 to 1: a phrase's match score, or 1 for a stated number, data or policy."""
    flagged: bool = False
    """The agent did not take the brief at its word (a value that would loosen company policy,
    an objective or target the planner does not offer), or the manager should check it."""
    note: str | None = None
    fallback: bool = False
    """Read by rules because the LLM was unavailable (ADR 0053): what the rules read from the
    brief is at most 0.7 confident."""


class QuestionReason(StrEnum):
    MISSING = "missing"
    """The brief does not say."""
    LOW_CONFIDENCE = "low_confidence"
    """The best reading scores below 0.7, or nothing in the data matches."""
    AMBIGUOUS = "ambiguous"
    """A second reading scores within 0.1 of the best."""


class ClarificationQuestion(BaseModel):
    """A specific question the agent asks instead of guessing (AG-02)."""

    model_config = ConfigDict(frozen=True)

    id: str
    """Stable within a round: the key its answer is given under."""
    field: str
    question: str
    reason: QuestionReason
    suggestions: tuple[str, ...] = ()
    """Readings the data allows, best first, for the manager to pick from or ignore."""


class Clarification(BaseModel):
    """A question the agent asked and the manager's answer, in their own words."""

    model_config = ConfigDict(frozen=True)

    question: ClarificationQuestion
    answer: str
