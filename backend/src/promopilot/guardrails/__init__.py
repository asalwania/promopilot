"""Deterministic guardrails (SPEC §9.6, ADR 0028): plan validation and numeric grounding.

`validate_plan` checks every hard constraint on a plan's own plan-time numbers (ADR 0012).
`check_numeric_grounding` checks that every number in a text comes from tool outputs.
"""

from promopilot.guardrails.grounding import GroundingReport, check_numeric_grounding
from promopilot.guardrails.validation import (
    LineFacts,
    PlanFacts,
    SkuFacts,
    Violation,
    ViolationCode,
    validate_plan,
)

__all__ = [
    "GroundingReport",
    "LineFacts",
    "PlanFacts",
    "SkuFacts",
    "Violation",
    "ViolationCode",
    "check_numeric_grounding",
    "validate_plan",
]
