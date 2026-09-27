"""Violations: broken hard constraints of a plan, found by plan validation (ADR 0028).

They live in the domain because a plan revision carries its unresolved ones as open issues
(ADR 0046).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from promopilot.domain.vocabulary import Region


class ViolationCode(StrEnum):
    BUDGET = "BUDGET"
    REGIONAL_BUDGET = "REGIONAL_BUDGET"
    MIN_MARGIN = "MIN_MARGIN"
    MARGIN_FLOOR = "MARGIN_FLOOR"
    STOCK = "STOCK"
    MAX_DISCOUNT = "MAX_DISCOUNT"
    BELOW_COST = "BELOW_COST"
    WINDOW = "WINDOW"
    MAX_SKUS = "MAX_SKUS"
    DUPLICATE_LINE = "DUPLICATE_LINE"
    CLEARANCE_TARGET = "CLEARANCE_TARGET"
    KVI_TOLERANCE = "KVI_TOLERANCE"


class Violation(BaseModel):
    """One broken hard constraint, specific enough for the planner to fix."""

    model_config = ConfigDict(frozen=True)

    code: ViolationCode
    message: str
    sku_id: str | None = None
    region: Region | None = None
    actual: float | None = None
    limit: float | None = None
