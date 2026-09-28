"""Shared domain value types (ADR 0009): immutable, logic-free, named from CONTEXT.md."""

from promopilot.domain.comparison import MechanismOption, MechanismOutcome
from promopilot.domain.explanation import ExplanationSource, FallbackReason, PlanExplanation
from promopilot.domain.plan import PlanLine, PromoPlan
from promopilot.domain.policy import CompanyPolicy, PolicyFinding
from promopilot.domain.request import ClearanceTarget, PlanningRequest, PromoWindow, Scope
from promopilot.domain.revision import PlanRevision, PlanRevisionLine
from promopilot.domain.selection import (
    BindingConstraint,
    BindingEvidence,
    ClearanceShortfall,
    ConstraintKind,
    ConstraintSource,
    NotSelectedOption,
    NotSelectedReason,
    PruneReason,
    Relaxation,
    RelaxedConstraint,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    WhyChosen,
)
from promopilot.domain.session import DecisionKind, PlanDecision, PlanningSession, SessionStatus
from promopilot.domain.simulation import (
    CompetitorReaction,
    LineSimulation,
    Percentiles,
    PlanSimulation,
    RegionStockout,
    SimulatedOutcomes,
)
from promopilot.domain.violation import Violation, ViolationCode
from promopilot.domain.vocabulary import Mechanism, Region, Segment, TargetSegment, Week

__all__ = [
    "BindingConstraint",
    "BindingEvidence",
    "ClearanceShortfall",
    "ClearanceTarget",
    "CompanyPolicy",
    "CompetitorReaction",
    "ConstraintKind",
    "ConstraintSource",
    "DecisionKind",
    "ExplanationSource",
    "FallbackReason",
    "LineSimulation",
    "Mechanism",
    "MechanismOption",
    "MechanismOutcome",
    "NotSelectedOption",
    "NotSelectedReason",
    "Percentiles",
    "PlanDecision",
    "PlanExplanation",
    "PlanLine",
    "PlanRevision",
    "PlanRevisionLine",
    "PlanSimulation",
    "PlanningRequest",
    "PlanningSession",
    "PolicyFinding",
    "PromoPlan",
    "PromoWindow",
    "PruneReason",
    "Region",
    "RegionStockout",
    "Relaxation",
    "RelaxedConstraint",
    "Scope",
    "Segment",
    "SelectionReason",
    "SelectionReasonCode",
    "SessionStatus",
    "SimulatedOutcomes",
    "SolveStatus",
    "TargetSegment",
    "Violation",
    "ViolationCode",
    "Week",
    "WhyChosen",
]
