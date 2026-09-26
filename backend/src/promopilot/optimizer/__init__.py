"""The optimiser (SPEC §9.3-9.4): promo option generation, then CP-SAT selection."""

from promopilot.domain import SolveStatus
from promopilot.optimizer.options import (
    DEPTHS,
    P90_Z,
    TABLE_COLUMNS,
    FittedOptionFacts,
    OptionContext,
    OptionForecast,
    PromoOptions,
    PruneReason,
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
    "FittedOptionFacts",
    "OptimisationResult",
    "OptionContext",
    "OptionFacts",
    "OptionForecast",
    "PromoOptions",
    "PruneReason",
    "SolveStatus",
    "SolverSettings",
    "generate_options",
    "solve",
]
