"""A plan revision's Monte Carlo simulation: ranges of outcomes and stock-out risk (SPEC §9.5,
F-06 AC3, F-09, ADR 0042)."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain.vocabulary import Region


class Percentiles(BaseModel):
    """The 10th, 50th and 90th percentiles of one simulated metric across the runs."""

    model_config = ConfigDict(frozen=True)

    p10: float
    p50: float
    p90: float

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("percentiles must satisfy p10 <= p50 <= p90")
        return self


class SimulatedOutcomes(BaseModel):
    """Ranges over the promo weeks, units capped at pooled available stock (ADR 0004, 0011).

    Units and sell-through are the anchor SKU's; revenue, gross profit and promo spend
    include a BUNDLE's partner (ADR 0017). Margin is gross profit over revenue in each run
    (0 in a run with no revenue). Sell-through is None when there is no available stock.
    """

    model_config = ConfigDict(frozen=True)

    units: Percentiles
    revenue: Percentiles
    gross_profit: Percentiles
    margin: Percentiles
    promo_spend: Percentiles
    sell_through: Percentiles | None


class LineSimulation(SimulatedOutcomes):
    """One plan line's simulated ranges, identified by its SKU and region."""

    sku_id: str
    region: Region
    stockout_probability: float = Field(ge=0, le=1)
    """The share of runs in which demand reached the available stock of the anchor or a
    BUNDLE's partner."""


class RegionStockout(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: Region
    stockout_probability: float = Field(ge=0, le=1)
    """The share of runs in which at least one of the region's plan lines ran out."""


class CompetitorReaction(BaseModel):
    """The competitor-reaction scenario (F-09 AC2, ADR 0045): in each run, each plan line's
    competitor matches its discount with this probability, independently of the other lines."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    match_probability: float = Field(
        ge=0,
        le=1,
        description="Chance, per plan line and run, that the competitor matches our discount.",
    )


class PlanSimulation(BaseModel):
    """What `simulate` returns for a promo plan, and what a plan revision stores."""

    model_config = ConfigDict(frozen=True)

    n_runs: int = Field(ge=1)
    seed: int
    competitor_reaction: CompetitorReaction | None = None
    """The scenario simulated; None when the competitor never reacts (ADR 0045)."""
    lines: tuple[LineSimulation, ...] = ()
    """In plan order."""
    total: SimulatedOutcomes
    """Percentiles of each run's plan totals, not sums of line percentiles."""
    regions: tuple[RegionStockout, ...] = ()
    """Each region with a plan line, in Region order."""
