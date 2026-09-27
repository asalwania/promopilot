"""Shared domain value types (ADR 0009): immutable, logic-free, named from CONTEXT.md."""

from promopilot.domain.comparison import MechanismOption, MechanismOutcome
from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import CompanyPolicy
from promopilot.domain.request import PlanningRequest, PromoWindow, Scope
from promopilot.domain.revision import PlanRevision, PlanRevisionLine
from promopilot.domain.selection import (
    BindingConstraint,
    BindingEvidence,
    ConstraintKind,
    ConstraintSource,
    NotSelectedOption,
    NotSelectedReason,
    PruneReason,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    WhyChosen,
)
from promopilot.domain.session import PlanningSession, SessionStatus
from promopilot.domain.simulation import (
    LineSimulation,
    Percentiles,
    PlanSimulation,
    RegionStockout,
    SimulatedOutcomes,
)
from promopilot.domain.vocabulary import Mechanism, Region, Segment, TargetSegment, Week

__all__ = [
    "BindingConstraint",
    "BindingEvidence",
    "CompanyPolicy",
    "ConstraintKind",
    "ConstraintSource",
    "LineSimulation",
    "Mechanism",
    "MechanismOption",
    "MechanismOutcome",
    "NotSelectedOption",
    "NotSelectedReason",
    "Percentiles",
    "PlanLine",
    "PlanRevision",
    "PlanRevisionLine",
    "PlanSimulation",
    "PlanningRequest",
    "PlanningSession",
    "PromoPlan",
    "PromoWindow",
    "PruneReason",
    "Region",
    "RegionStockout",
    "Scope",
    "Segment",
    "SelectionReason",
    "SelectionReasonCode",
    "SessionStatus",
    "SimulatedOutcomes",
    "SolveStatus",
    "TargetSegment",
    "Week",
    "WhyChosen",
]
