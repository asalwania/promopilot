"""The optimiser (SPEC §9.3-9.4): promo option generation, then CP-SAT selection."""

from promopilot.domain import PruneReason, SolveStatus
from promopilot.optimizer.options import (
    DEPTHS,
    P90_Z,
    TABLE_COLUMNS,
    ClearanceBaseline,
    FittedOptionFacts,
    OptionContext,
    OptionForecast,
    PriceMatch,
    PromoOptions,
    generate_options,
)
from promopilot.optimizer.solver import (
    OptimisationResult,
    OptionFacts,
    SolverSettings,
    solve,
)
from promopilot.optimizer.store import CandidateSet, CandidateStore

__all__ = [
    "DEPTHS",
    "P90_Z",
    "TABLE_COLUMNS",
    "CandidateSet",
    "CandidateStore",
    "ClearanceBaseline",
    "FittedOptionFacts",
    "OptimisationResult",
    "OptionContext",
    "OptionFacts",
    "OptionForecast",
    "PriceMatch",
    "PromoOptions",
    "PruneReason",
    "SolveStatus",
    "SolverSettings",
    "generate_options",
    "solve",
]
