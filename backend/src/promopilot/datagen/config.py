"""Generator configuration: the SPEC §8.1 defaults in config.yaml, overridable per call."""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import Mechanism, Region, Segment

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

Range = tuple[float, float]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SubcategorySpec(_Frozen):
    name: str
    packs: dict[str, float]
    """Pack size label -> reference shelf price in rupees before the brand premium."""


class CategorySpec(_Frozen):
    name: str
    margin: Range
    brands: list[str] = Field(min_length=1)
    subcategories: list[SubcategorySpec] = Field(min_length=1)


class CatalogueConfig(_Frozen):
    skus_per_category: int = Field(ge=1)
    categories_limit: int | None = Field(default=None, ge=1)
    kvi_share: float = Field(ge=0, le=1)
    brand_premium: Range
    categories: list[CategorySpec] = Field(min_length=1)

    def model_post_init(self, context: Any, /) -> None:
        if self.categories_limit is not None:
            object.__setattr__(self, "categories", self.categories[: self.categories_limit])
            object.__setattr__(self, "categories_limit", None)


class SegmentMixConfig(_Frozen):
    base: dict[Segment, float]
    region_concentration: float = Field(gt=0)
    store_concentration: float = Field(gt=0)


class HolidaySpec(_Frozen):
    name: str
    intensity: float = Field(gt=0, le=1)
    dates: list[date]
    regions: list[Region] | None = None
    """None means a national festival."""


class DemandConfig(_Frozen):
    base_weekly_units: Range
    kvi_volume_multiplier: float = Field(gt=0)
    store_level_sd: float = Field(ge=0)
    segment_affinity_sd: float = Field(ge=0)
    season_amplitude: Range
    holiday_sensitivity: Range
    elasticity_subcategory_mean: Range
    elasticity_sku_sd: float = Field(ge=0)
    kvi_elasticity_shift: float
    elasticity_bounds: Range
    segment_elasticity_multiplier: dict[Segment, float]
    competitor_sensitivity: Range
    kvi_competitor_multiplier: float = Field(gt=0)
    substitute_share: float = Field(ge=0, le=1)
    substitute_theta: Range
    complement_theta: Range
    complement_categories: list[tuple[str, str]]
    mechanism_effect: dict[Mechanism, Range]
    pull_forward: Range
    pull_forward_window_weeks: int = Field(ge=1)
    dispersion: Range


class PromotionsConfig(_Frozen):
    share: float = Field(gt=0, lt=0.5)
    min_gap_weeks: int = Field(ge=0)
    mechanism_weights: dict[Mechanism, float]
    depth_levels: list[int]
    bundle_depth_levels: list[int]
    all_customers_share: float = Field(ge=0, le=1)


class CompetitorsConfig(_Frozen):
    price_level: Range
    weekly_noise_sd: float = Field(ge=0)
    promo_probability: float = Field(ge=0, le=1)
    promo_depth: Range
    promo_weeks: tuple[int, int]
    aggressive_region: Region
    aggressive_promo_probability: float = Field(ge=0, le=1)
    aggressive_kvi_price_level: Range


class GeneratorConfig(_Frozen):
    seed: int
    start_date: date
    history_weeks: int = Field(ge=8)
    horizon_weeks: int = Field(ge=1)
    regions: list[Region] = Field(min_length=1)
    stores_per_region: int = Field(ge=1)
    baskets: int = Field(ge=0)
    complement_pairs: int = Field(ge=0)
    cities: dict[Region, list[str]]
    catalogue: CatalogueConfig
    segment_mix: SegmentMixConfig
    holiday_lead_in: float = Field(ge=0, le=1)
    holidays: list[HolidaySpec]
    demand: DemandConfig
    promotions: PromotionsConfig
    competitors: CompetitorsConfig

    @property
    def total_weeks(self) -> int:
        return self.history_weeks + self.horizon_weeks


def load_config(
    path: Path | None = None, *, overrides: dict[str, Any] | None = None
) -> GeneratorConfig:
    """Read a YAML config (the packaged defaults by default) and deep-merge overrides."""
    raw = yaml.safe_load((path or DEFAULT_CONFIG_PATH).read_text(encoding="utf-8"))
    if path is not None:
        raw = _merge(yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")), raw)
    return GeneratorConfig.model_validate(_merge(raw, overrides or {}))


def _merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged
