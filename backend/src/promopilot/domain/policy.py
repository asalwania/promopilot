"""Company policy: the parent company's standing rules, outside any brief (ADR 0007)."""

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain.vocabulary import Mechanism


def _default_fixed_costs() -> dict[Mechanism, float]:
    return {
        Mechanism.PCT_OFF: 500.0,
        Mechanism.FIXED_PRICE: 500.0,
        Mechanism.BOGO: 750.0,
        Mechanism.BUNDLE: 1000.0,
    }


class CompanyPolicy(BaseModel):
    """A brief may tighten these rules but never loosen them. Money is in rupees."""

    model_config = ConfigDict(frozen=True)

    margin_floor: float = Field(default=0.15, ge=0, lt=1)
    max_discount_pct: int = Field(default=50, ge=1, le=100)
    undercut_threshold: float = Field(default=0.05, ge=0, lt=1)
    """A KVI is undercut when its competitor price index is below 1 minus this."""
    kvi_price_tolerance: float = Field(default=0.02, ge=0, lt=1)
    kvi_price_tolerance_enabled: bool = False
    overstock_threshold_weeks: float = Field(default=8, gt=0)
    """A SKU in a region is overstocked when its cover exceeds this many weeks."""
    write_off_rate: float = Field(default=0.30, ge=0, le=1)
    fixed_cost_per_line_week: dict[Mechanism, float] = Field(default_factory=_default_fixed_costs)
    max_promoted_skus_per_category_per_region: int = Field(default=10, ge=1)
    strong_substitute_min_theta: float = Field(default=0.35, gt=0)
    """Two SKUs the relations model detects as substitutes, with an estimated cross-price
    effect θ at least this, are strong substitutes: never promoted together (ADR 0075)."""


class PolicyFinding(BaseModel):
    """A brief value that would loosen company policy: planning keeps the policy value and
    flags it (ADR 0007, ADR 0040)."""

    model_config = ConfigDict(frozen=True)

    field: str
    """The planning-request field, e.g. min_margin."""
    requested: float
    applied: float
    message: str
