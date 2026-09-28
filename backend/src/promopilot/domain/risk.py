"""Risk findings: what the Critic's risk review flags in a plan that breaks no hard constraint
(AG-04, ADR 0051), and the open issues a plan revision carries (ADR 0046)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from promopilot.domain.violation import Violation
from promopilot.domain.vocabulary import Region


class RiskCode(StrEnum):
    OVER_CONCENTRATION = "OVER_CONCENTRATION"
    """One plan line, category or region takes too much of the plan's promo spend."""
    HEAVY_CANNIBALISATION = "HEAVY_CANNIBALISATION"
    """A plan line's substitutes lose too much of the incremental profit it makes."""
    STOCKOUT_RISK = "STOCKOUT_RISK"
    """A plan line runs out of stock in too many of the simulation's runs."""


class RiskFinding(BaseModel):
    """One risk the Critic's review found, with feedback specific enough for the planner to act
    on. Its numbers come from the plan's tool outputs, never from the LLM."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["risk"] = "risk"
    code: RiskCode
    message: str
    """What is wrong, with the numbers that show it."""
    feedback: str
    """What the planner could do about it: the review's template, or the LLM's wording of it
    when that passes numeric grounding."""
    sku_id: str | None = None
    region: Region | None = None
    category: str | None = None
    actual: float
    """A share of promo spend or of incremental profit, or a stock-out probability."""
    limit: float
    """The threshold `actual` crossed."""


type OpenIssue = Violation | RiskFinding
"""A violation or a risk finding a plan revision still has when it goes for approval."""
