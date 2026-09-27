"""The planning request: the structured, validated reading of a brief (E3 minimum; E6 and E8
extend)."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain.vocabulary import Region, Week


class Scope(BaseModel):
    """The regions and categories a planning request covers, optionally narrowed to SKUs."""

    model_config = ConfigDict(frozen=True)

    regions: tuple[Region, ...] = Field(min_length=1)
    categories: tuple[str, ...] = Field(min_length=1)
    sku_ids: tuple[str, ...] = ()


class PromoWindow(BaseModel):
    """The future weeks, inclusive, in which a plan's promotions must start and end."""

    model_config = ConfigDict(frozen=True)

    start_week: Week
    end_week: Week

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_week < self.start_week:
            raise ValueError("a promo window cannot end before it starts")
        return self


class ClearanceTarget(BaseModel):
    """The minimum sell-through the brief asks for a SKU it names for clearance, in every
    region of the scope (ADR 0014, ADR 0040)."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    sell_through: float = Field(gt=0, le=1)
    """Expected units sold over the promo window / available stock, as a fraction."""


class PlanningRequest(BaseModel):
    """Money is in rupees (ADR 0015). The brief's optional constraints may only tighten
    company policy; a value that would loosen it is kept here as read, and planning applies
    the policy value instead and flags it (ADR 0007, ADR 0040)."""

    model_config = ConfigDict(frozen=True)

    as_of_week: Week
    scope: Scope
    promo_window: PromoWindow
    marketing_budget: float = Field(gt=0)
    min_margin: float | None = Field(default=None, ge=0, lt=1)
    clearance_targets: tuple[ClearanceTarget, ...] = ()
    """SKUs the brief names for clearance; only these get a clearance target (ADR 0014)."""
    regional_budget_caps: dict[Region, float] = Field(default_factory=dict)
    """Optional caps on the promo cost spent in a region, for regions in scope (rupees)."""
    kvi_price_tolerance: float | None = Field(default=None, ge=0, lt=1)
    """Keep each KVI's promo price at most this far above the competitor price. None leaves
    the company-policy setting (off by default, ADR 0007)."""
    max_promoted_skus_per_category_per_region: int | None = Field(default=None, ge=1)
    """A tighter cap than company policy's on promoted SKUs per category per region."""

    @model_validator(mode="after")
    def _window_after_as_of_week(self) -> Self:
        if self.promo_window.start_week <= self.as_of_week:
            raise ValueError("the promo window must lie strictly after the as-of week (ADR 0008)")
        return self

    @model_validator(mode="after")
    def _one_target_per_sku(self) -> Self:
        sku_ids = [target.sku_id for target in self.clearance_targets]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("a SKU has at most one clearance target")
        return self

    @model_validator(mode="after")
    def _caps_in_scope(self) -> Self:
        outside = [r for r in self.regional_budget_caps if r not in self.scope.regions]
        if outside:
            raise ValueError(f"regional budget caps for regions not in the scope: {outside}")
        if any(cap <= 0 for cap in self.regional_budget_caps.values()):
            raise ValueError("a regional budget cap must be positive")
        return self
