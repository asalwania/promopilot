"""Plan lines and promo plans."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain.vocabulary import Mechanism, Region, TargetSegment, Week


class PlanLine(BaseModel):
    """A promo option selected into a promo plan: one (SKU, region) decision (ADR 0004)."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    region: Region
    mechanism: Mechanism
    depth_pct: int = Field(ge=1, le=100)
    duration_weeks: int = Field(ge=1, le=4)
    start_week: Week
    target_segment: TargetSegment
    bundle_partner_sku_id: str | None = None

    @model_validator(mode="after")
    def _mechanism_rules(self) -> Self:
        if self.mechanism is Mechanism.BUNDLE:
            if self.bundle_partner_sku_id is None:
                raise ValueError("a BUNDLE needs a bundle partner SKU")
            if self.bundle_partner_sku_id == self.sku_id:
                raise ValueError("a BUNDLE cannot name its own SKU as its own partner")
        elif self.bundle_partner_sku_id is not None:
            raise ValueError("only a BUNDLE plan line may name a bundle partner SKU")
        if self.mechanism is Mechanism.BOGO and self.depth_pct != 50:
            raise ValueError("BOGO is buy-one-get-one only: depth_pct must be 50")
        return self

    @property
    def skus(self) -> tuple[str, ...]:
        """The SKUs this line occupies in its region: the anchor, plus a BUNDLE's partner."""
        if self.bundle_partner_sku_id is None:
            return (self.sku_id,)
        return (self.sku_id, self.bundle_partner_sku_id)


class PromoPlan(BaseModel):
    """The set of plan lines produced for a planning request."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[PlanLine, ...] = ()

    @model_validator(mode="after")
    def _one_line_per_sku_per_region(self) -> Self:
        # A BUNDLE partner is locked: it counts as occupying its region (ADR 0014).
        seen: set[tuple[str, Region]] = set()
        for line in self.lines:
            for sku_id in line.skus:
                key = (sku_id, line.region)
                if key in seen:
                    raise ValueError(
                        f"a plan has at most one plan line per SKU per region: "
                        f"{sku_id} appears twice in {line.region}"
                    )
                seen.add(key)
        return self
