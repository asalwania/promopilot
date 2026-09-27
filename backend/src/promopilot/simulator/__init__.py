"""The Monte Carlo simulator (SPEC §9.5, ADR 0042): ranges of a promo plan's outcomes."""

from promopilot.simulator.simulate import (
    DEFAULT_RUNS,
    MAX_RUNS,
    MIN_RUNS,
    ResponseSource,
    SimulationInputs,
    SimulationSettings,
    simulate,
)

__all__ = [
    "DEFAULT_RUNS",
    "MAX_RUNS",
    "MIN_RUNS",
    "ResponseSource",
    "SimulationInputs",
    "SimulationSettings",
    "simulate",
]
