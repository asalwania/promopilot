"""The optimiser (SPEC §9.3-9.4): promo option generation, then selection (#34)."""

from promopilot.optimizer.options import (
    DEPTHS,
    P90_Z,
    TABLE_COLUMNS,
    OptionContext,
    OptionForecast,
    PromoOptions,
    PruneReason,
    generate_options,
)
from promopilot.optimizer.store import CandidateSet, CandidateStore

__all__ = [
    "DEPTHS",
    "P90_Z",
    "TABLE_COLUMNS",
    "CandidateSet",
    "CandidateStore",
    "OptionContext",
    "OptionForecast",
    "PromoOptions",
    "PruneReason",
    "generate_options",
]
