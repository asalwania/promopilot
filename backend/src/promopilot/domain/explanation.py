"""Plan explanations: a summary of a plan revision and a rationale per plan line, whose every
number is grounded in tool outputs (SPEC SF-05, §9.6, ADR 0050)."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class ExplanationSource(StrEnum):
    LLM = "llm"
    """The Explainer's LLM wrote it, and it passed numeric grounding."""
    TEMPLATE = "template"
    """The deterministic template wrote it from the plan revision's own numbers."""


class FallbackReason(StrEnum):
    """Why the template explained a plan revision instead of the LLM."""

    UNGROUNDED = "ungrounded"
    """Both LLM answers cited a number no tool output supports."""
    INVALID_ANSWER = "invalid_answer"
    """Both LLM answers were blank or missed, repeated or invented a plan line."""
    LLM_UNAVAILABLE = "llm_unavailable"
    """The LLM failed after its retries and fallback provider, or no cassette was recorded
    for the request when replaying."""


class PlanExplanation(BaseModel):
    """What the Explainer wrote for one plan revision."""

    model_config = ConfigDict(frozen=True)

    summary: str
    rationales: tuple[str, ...] = ()
    """One per plan line, in plan-line order."""
    source: ExplanationSource
    fallback_reason: FallbackReason | None = None
    """Why the LLM's explanation was not used; None when it was, or when no LLM was asked."""

    @model_validator(mode="after")
    def _fallback_only_for_a_template(self) -> Self:
        if self.fallback_reason is not None and self.source is not ExplanationSource.TEMPLATE:
            raise ValueError("only a template explanation has a fallback reason")
        return self
