"""The planning request: the structured, validated reading of a brief (E3 minimum; E8 extends)."""

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


class PlanningRequest(BaseModel):
    """Money is in rupees (ADR 0015)."""

    model_config = ConfigDict(frozen=True)

    as_of_week: Week
    scope: Scope
    promo_window: PromoWindow
    marketing_budget: float = Field(gt=0)
    min_margin: float | None = Field(default=None, ge=0, lt=1)

    @model_validator(mode="after")
    def _window_after_as_of_week(self) -> Self:
        if self.promo_window.start_week <= self.as_of_week:
            raise ValueError("the promo window must lie strictly after the as-of week (ADR 0008)")
        return self
