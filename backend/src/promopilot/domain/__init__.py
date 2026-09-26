"""Shared domain value types (ADR 0009): immutable, logic-free, named from CONTEXT.md."""

from promopilot.domain.plan import PlanLine, PlanRevision, PlanRevisionLine, PromoPlan
from promopilot.domain.policy import CompanyPolicy
from promopilot.domain.request import PlanningRequest, PromoWindow, Scope
from promopilot.domain.session import PlanningSession, SessionStatus
from promopilot.domain.vocabulary import Mechanism, Region, Segment, TargetSegment, Week

__all__ = [
    "CompanyPolicy",
    "Mechanism",
    "PlanLine",
    "PlanRevision",
    "PlanRevisionLine",
    "PlanningRequest",
    "PlanningSession",
    "PromoPlan",
    "PromoWindow",
    "Region",
    "Scope",
    "Segment",
    "SessionStatus",
    "TargetSegment",
    "Week",
]
