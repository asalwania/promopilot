"""Shared domain value types (ADR 0009): immutable, logic-free, named from CONTEXT.md."""

from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import CompanyPolicy
from promopilot.domain.vocabulary import Mechanism, Region, Segment, TargetSegment, Week

__all__ = [
    "CompanyPolicy",
    "Mechanism",
    "PlanLine",
    "PromoPlan",
    "Region",
    "Segment",
    "TargetSegment",
    "Week",
]
