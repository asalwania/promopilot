"""Shared domain value types (ADR 0009): immutable, logic-free, named from CONTEXT.md."""

from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import CompanyPolicy
from promopilot.domain.request import PlanningRequest, PromoWindow, Scope
from promopilot.domain.revision import PlanRevision, PlanRevisionLine
from promopilot.domain.selection import (
    BindingConstraint,
    ConstraintKind,
    ConstraintSource,
    NotSelectedOption,
    NotSelectedReason,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    WhyChosen,
)
from promopilot.domain.session import PlanningSession, SessionStatus
from promopilot.domain.vocabulary import Mechanism, Region, Segment, TargetSegment, Week

__all__ = [
    "BindingConstraint",
    "CompanyPolicy",
    "ConstraintKind",
    "ConstraintSource",
    "Mechanism",
    "NotSelectedOption",
    "NotSelectedReason",
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
    "SelectionReason",
    "SelectionReasonCode",
    "SessionStatus",
    "SolveStatus",
    "TargetSegment",
    "Week",
    "WhyChosen",
]
