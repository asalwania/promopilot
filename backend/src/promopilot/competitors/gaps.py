"""Competitor gaps and KVI undercuts at an as-of week (SPEC §9, ADR 0007, ADR 0031).

The competitor price index (CPI) of a SKU in a region is the competitor's latest price before
the as-of week divided by our base price. Its gap is 1 minus CPI: positive when the competitor is
cheaper. A KVI is **undercut** when its CPI is strictly below 1 minus the company-policy undercut
threshold, so with the default 5% a 4.9% gap is not undercut and a 5.1% gap is.
"""

from collections.abc import Sequence
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import CompanyPolicy, PlanLine, Region, Week
from promopilot.economics import effective_unit_price


class CompetitorGap(BaseModel):
    """One SKU in one region against the competitor's latest price before the as-of week."""

    model_config = ConfigDict(frozen=True)

    region: Region
    sku_id: str
    name: str
    category: str
    subcategory: str
    is_kvi: bool
    base_price: float = Field(description="Our regular shelf price in rupees.")
    competitor_price: float = Field(description="The competitor's latest price in rupees.")
    competitor_on_promo: bool = Field(description="Whether that price was a competitor promo.")
    price_week: Week = Field(description="The week of that price, before the as-of week.")
    cpi: float = Field(description="Competitor price index: competitor price ÷ base price.")
    gap: float = Field(description="1 minus CPI: how much cheaper the competitor is (< 0: dearer).")
    undercut: bool = Field(description="A KVI whose CPI is below 1 minus the undercut threshold.")


class CompetitorGaps(BaseModel):
    """The gaps for a scope, widest first, with the company-policy rules they were judged by."""

    model_config = ConfigDict(frozen=True)

    as_of_week: Week
    undercut_threshold: float
    kvi_price_tolerance: float = Field(
        description="How far above the competitor a KVI promo price may sit, when enabled."
    )
    gaps: tuple[CompetitorGap, ...]

    def within_kvi_tolerance(self, line: PlanLine) -> bool:
        """Whether a plan line keeps its KVIs within the price tolerance (F-08 AC3).

        The rule is one-sided: each KVI the line promotes (a BUNDLE promotes both SKUs) passes
        when its effective unit price under the line's mechanism (BOGO is 50% off) is at most
        the competitor price x (1 + tolerance). Pricing below the competitor always passes.
        Non-KVIs always pass, and so does a SKU with no known competitor price in these gaps.
        The rule is off unless the planning request enables it; the caller decides that.
        """
        known = {(gap.region, gap.sku_id): gap for gap in self.gaps}
        for sku_id in line.skus:
            gap = known.get((line.region, sku_id))
            if gap is None or not gap.is_kvi:
                continue
            price = effective_unit_price(line.mechanism, gap.base_price, line.depth_pct)
            if price > gap.competitor_price * (1 + self.kvi_price_tolerance):
                return False
        return True

    def undercut_response(self, lines: Sequence[PlanLine]) -> tuple[str, ...]:
        """The planner's explanation of how a plan answers undercut KVIs (F-08 AC2, ADR 0049).

        One sentence per undercut KVI, widest gap first, with its gap to one decimal and both
        prices ("Competitor is 5.1% cheaper on K2 (Rice 5kg) in North (₹94.90 vs ₹100.00)."),
        then how many the plan matches. A KVI is matched when a plan line in its region
        promotes it (a BUNDLE promotes both SKUs) at an effective unit price at or below the
        competitor's. Empty when no KVI is undercut. Every number comes from these gaps, so the
        sentences pass numeric grounding against them.
        """
        undercut = [gap for gap in self.gaps if gap.undercut]
        if not undercut:
            return ()
        stated = [
            f"Competitor is {gap.gap * 100:.1f}% cheaper on {gap.sku_id} ({gap.name}) in "
            f"{gap.region.value} (₹{gap.competitor_price:,.2f} vs ₹{gap.base_price:,.2f})."
            for gap in undercut
        ]
        matched = sum(1 for gap in undercut if _matched(gap, lines))
        return (*stated, _response(matched, len(undercut)))


def _matched(gap: CompetitorGap, lines: Sequence[PlanLine]) -> bool:
    return any(
        line.region == gap.region
        and gap.sku_id in line.skus
        and effective_unit_price(line.mechanism, gap.base_price, line.depth_pct)
        <= gap.competitor_price
        for line in lines
    )


def _response(matched: int, undercut: int) -> str:
    if matched == 0:
        return (
            "Not matching on any undercut SKU: no price match paid for itself within the "
            "brief's constraints, so the plan protects margin."
        )
    them = "it" if matched == 1 else "them"
    if matched == undercut:
        skus = "SKU" if matched == 1 else "SKUs"
        return f"Matching on {matched} {skus}: the plan prices {them} at or below the competitor."
    return (
        f"Matching on {matched} of {undercut} undercut SKUs: the plan prices {them} at or "
        "below the competitor."
    )


def competitor_gaps(
    products: pd.DataFrame,
    competitor_prices: pd.DataFrame,
    *,
    as_of_week: int,
    policy: CompanyPolicy,
    regions: Sequence[Region] | None = None,
    categories: Sequence[str] | None = None,
    sku_ids: Sequence[str] | None = None,
    kvi_only: bool = False,
) -> CompetitorGaps:
    """Gaps from the product catalogue and any competitor price history.

    Prices at or after the as-of week are ignored. A SKU and region with no earlier price is
    left out. Filters narrow the rows; an unknown SKU or category raises `ValueError`.
    """
    _check_known(products, "sku_id", sku_ids, "SKU")
    _check_known(products, "category", categories, "category")
    visible = competitor_prices[competitor_prices["week_id"] < as_of_week]
    latest = visible.sort_values("week_id").drop_duplicates(["region", "sku_id"], keep="last")
    rows = latest.merge(products, on="sku_id", validate="many_to_one")
    if regions is not None:
        rows = rows[rows["region"].isin([region.value for region in regions])]
    if categories is not None:
        rows = rows[rows["category"].isin(categories)]
    if sku_ids is not None:
        rows = rows[rows["sku_id"].isin(sku_ids)]
    if kvi_only:
        rows = rows[rows["is_kvi"]]
    rows = rows.assign(cpi=rows["competitor_price"] / rows["base_price"])
    rows = rows.assign(
        gap=1 - rows["cpi"],
        undercut=rows["is_kvi"] & (rows["cpi"] < 1 - policy.undercut_threshold),
        price_week=rows["week_id"],
    ).sort_values(["gap", "region", "sku_id"], ascending=[False, True, True])
    fields = list(CompetitorGap.model_fields)
    return CompetitorGaps(
        as_of_week=as_of_week,
        undercut_threshold=policy.undercut_threshold,
        kvi_price_tolerance=policy.kvi_price_tolerance,
        gaps=tuple(CompetitorGap.model_validate(row) for row in rows[fields].to_dict("records")),
    )


class CompetitorData(Protocol):
    """The as-of-week repositories the gaps are read from (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame: ...


async def read_competitor_gaps(
    data: CompetitorData,
    *,
    as_of_week: int,
    policy: CompanyPolicy,
    regions: Sequence[Region] | None = None,
    categories: Sequence[str] | None = None,
    sku_ids: Sequence[str] | None = None,
    kvi_only: bool = False,
) -> CompetitorGaps:
    """`competitor_gaps` over the repositories' latest competitor prices."""
    return competitor_gaps(
        await data.products(),
        await data.latest_competitor_prices(as_of_week),
        as_of_week=as_of_week,
        policy=policy,
        regions=regions,
        categories=categories,
        sku_ids=sku_ids,
        kvi_only=kvi_only,
    )


def _check_known(
    products: pd.DataFrame, column: str, wanted: Sequence[str] | None, what: str
) -> None:
    if wanted is None:
        return
    unknown = sorted(set(wanted) - set(products[column]))
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)}")
