"""Mechanism comparisons: each mechanism's best promo option for a SKU in a region, next to
the plan line's own (SPEC F-02, ADR 0041)."""

from pydantic import BaseModel, ConfigDict

from promopilot.domain.plan import PlanLine
from promopilot.domain.selection import PruneReason
from promopilot.domain.vocabulary import Mechanism


class MechanismOption(BaseModel):
    """One promo option's expected numbers, as its prediction gave them (rupees, units over
    its promo weeks; a BUNDLE's money fields include its partner)."""

    model_config = ConfigDict(frozen=True)

    option: PlanLine
    anchor_sku_id: str
    partner_sku_id: str | None = None
    """A BUNDLE's complement; None for every other mechanism."""
    basket_lift: float | None = None
    """How much more often the pair is bought together than by chance; BUNDLE only."""
    effective_price: float
    """What the shopper pays per unit of the anchor SKU (ADR 0005, ADR 0015)."""
    partner_effective_price: float | None = None
    """What the shopper pays per unit of a BUNDLE's partner."""
    units: float
    revenue: float
    gross_profit: float
    margin: float
    promo_cost: float
    incremental_profit: float
    cannibalised_profit: float
    halo_profit: float
    clearance_value: float
    value: float
    """incremental profit - cannibalisation + halo + clearance value: what the optimiser
    counts for the option on its own (ADR 0036)."""


class MechanismOutcome(BaseModel):
    """One mechanism in a comparison: its best option, or why it has none."""

    model_config = ConfigDict(frozen=True)

    mechanism: Mechanism
    best: MechanismOption | None
    """The mechanism's highest-value option, or the plan line itself when `chosen`; None when
    every option of the mechanism broke a per-line rule."""
    chosen: bool = False
    """Whether this is the plan line's own mechanism, shown with the plan line's option."""
    unavailable: tuple[PruneReason, ...] = ()
    """When `best` is None: the rules its options broke, in the order they are applied."""
