"""Deterministic guardrails (SPEC §9.6, ADR 0028): plan validation and numeric grounding.

`validate_plan` checks every hard constraint on a plan's own plan-time numbers (ADR 0012).
`plan_limits` applies the brief's tighten-only changes to company policy (ADR 0007, ADR 0040).
`check_numeric_grounding` checks that every number in a text comes from tool outputs.
"""

from promopilot.domain import Violation, ViolationCode
from promopilot.guardrails.grounding import GroundingReport, check_numeric_grounding
from promopilot.guardrails.limits import PlanLimits, plan_limits
from promopilot.guardrails.validation import (
    ClearanceFacts,
    LineFacts,
    PlanFacts,
    SkuFacts,
    validate_plan,
)

__all__ = [
    "ClearanceFacts",
    "GroundingReport",
    "LineFacts",
    "PlanFacts",
    "PlanLimits",
    "SkuFacts",
    "Violation",
    "ViolationCode",
    "check_numeric_grounding",
    "plan_limits",
    "validate_plan",
]
