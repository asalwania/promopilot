"""Deterministic guardrails (SPEC §9.6, ADR 0028): plan validation and numeric grounding.

`validate_plan` checks every hard constraint on a plan's own plan-time numbers (ADR 0012).
`plan_limits` applies the brief's tighten-only changes to company policy (ADR 0007, ADR 0040).
`review_risks` flags a plan's over-concentration, heavy cannibalisation and stock-out risk
(ADR 0051). `check_numeric_grounding` checks that every number in a text comes from tool
outputs, and `format_rupees`, `format_percent` and `format_units` show numbers so that it
always accepts them (ADR 0050). `diff_revisions` compares consecutive plan revisions
(ADR 0052). `read_stated_numbers` reads the rupees and percentages a brief states, for the
Context agent's fallback reading (ADR 0053).
"""

from promopilot.domain import Violation, ViolationCode
from promopilot.guardrails.diff import diff_revisions, request_changes
from promopilot.guardrails.formatting import format_percent, format_rupees, format_units
from promopilot.guardrails.grounding import GroundingReport, check_numeric_grounding
from promopilot.guardrails.limits import PlanLimits, plan_limits
from promopilot.guardrails.risks import RiskThresholds, review_risks
from promopilot.guardrails.stated import StatedKind, StatedNumber, read_stated_numbers
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
    "RiskThresholds",
    "SkuFacts",
    "StatedKind",
    "StatedNumber",
    "Violation",
    "ViolationCode",
    "check_numeric_grounding",
    "diff_revisions",
    "format_percent",
    "format_rupees",
    "format_units",
    "plan_limits",
    "read_stated_numbers",
    "request_changes",
    "review_risks",
    "validate_plan",
]
