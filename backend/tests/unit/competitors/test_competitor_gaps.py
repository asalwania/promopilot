"""Competitor gaps and KVI undercuts over hand-built prices (SPEC §9, ADR 0007, ADR 0031)."""

from typing import Any

import pandas as pd
import pytest

from promopilot.competitors import CompetitorGaps, competitor_gaps
from promopilot.domain import CompanyPolicy, PlanLine, Region

AS_OF = 10
POLICY = CompanyPolicy()

PRODUCTS = pd.DataFrame(
    [
        ("K1", "Atta 5kg", "Staples", "Flour", 100.0, True),
        ("K2", "Rice 5kg", "Staples", "Rice", 100.0, True),
        ("K3", "Oil 1L", "Staples", "Oil", 200.0, True),
        ("N1", "Namkeen 400g", "Snacks", "Namkeen", 100.0, False),
    ],
    columns=["sku_id", "name", "category", "subcategory", "base_price", "is_kvi"],
).assign(brand="B", pack_size="1", unit_cost=50.0)


def prices(*rows: tuple[int, str, str, float, bool]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["week_id", "region", "sku_id", "competitor_price", "competitor_on_promo"]
    )


PRICES = prices(
    (AS_OF - 1, "North", "K1", 95.1, False),  # a 4.9% gap
    (AS_OF - 1, "North", "K2", 94.9, True),  # a 5.1% gap
    (AS_OF - 1, "North", "N1", 80.0, True),  # a 20% gap, not a KVI
    (AS_OF - 1, "South", "K1", 110.0, False),  # dearer than us
    (AS_OF - 3, "South", "K3", 180.0, False),  # the last known price is older
)


def gaps(**filters: Any) -> CompetitorGaps:
    return competitor_gaps(PRODUCTS, PRICES, as_of_week=AS_OF, policy=POLICY, **filters)


def row(result: CompetitorGaps, region: str, sku_id: str) -> Any:
    [found] = [g for g in result.gaps if g.region == region and g.sku_id == sku_id]
    return found


def test_with_the_default_threshold_a_4_9_pct_gap_is_not_undercut_and_5_1_pct_is() -> None:
    result = gaps()

    assert row(result, "North", "K1").undercut is False
    assert row(result, "North", "K2").undercut is True


def test_a_gap_of_exactly_the_threshold_is_not_undercut() -> None:
    at_threshold = prices((AS_OF - 1, "North", "K1", 95.0, False))

    result = competitor_gaps(PRODUCTS, at_threshold, as_of_week=AS_OF, policy=POLICY)

    assert row(result, "North", "K1").undercut is False


def test_the_index_is_competitor_price_over_base_price_and_the_gap_is_one_minus_it() -> None:
    k2 = row(gaps(), "North", "K2")

    assert k2.cpi == pytest.approx(0.949)
    assert k2.gap == pytest.approx(0.051)
    assert k2.base_price == 100.0
    assert k2.competitor_price == 94.9
    assert k2.competitor_on_promo is True
    assert k2.price_week == AS_OF - 1
    assert (k2.name, k2.category, k2.subcategory, k2.is_kvi) == (
        "Rice 5kg",
        "Staples",
        "Rice",
        True,
    )
    south = row(gaps(), "South", "K1")
    assert south.gap == pytest.approx(-0.10)
    assert south.undercut is False


def test_only_a_kvi_can_be_undercut() -> None:
    namkeen = row(gaps(), "North", "N1")

    assert namkeen.gap == pytest.approx(0.20)
    assert namkeen.undercut is False


def test_the_threshold_comes_from_company_policy() -> None:
    strict = CompanyPolicy(undercut_threshold=0.04)

    result = competitor_gaps(PRODUCTS, PRICES, as_of_week=AS_OF, policy=strict)

    assert result.undercut_threshold == 0.04
    assert row(result, "North", "K1").undercut is True


def test_competitor_prices_at_or_after_the_as_of_week_are_invisible() -> None:
    with_future = pd.concat(
        [
            PRICES,
            prices(
                (AS_OF, "North", "K1", 50.0, True),
                (AS_OF + 2, "North", "K1", 50.0, True),
                (AS_OF, "East", "K1", 50.0, True),
            ),
        ]
    )

    result = competitor_gaps(PRODUCTS, with_future, as_of_week=AS_OF, policy=POLICY)

    assert result == gaps()
    assert row(result, "North", "K1").competitor_price == 95.1
    assert all(g.region != "East" for g in result.gaps)


def test_the_latest_price_before_the_as_of_week_is_used_and_pairs_without_one_are_left_out() -> (
    None
):
    history = pd.concat([PRICES, prices((AS_OF - 5, "North", "K1", 60.0, True))])

    result = competitor_gaps(PRODUCTS, history, as_of_week=AS_OF, policy=POLICY)

    assert row(result, "North", "K1").competitor_price == 95.1
    assert row(result, "South", "K3").price_week == AS_OF - 3
    keys = {(g.region, g.sku_id) for g in result.gaps}
    assert keys == {("North", "K1"), ("North", "K2"), ("North", "N1"), ("South", "K1"),
                    ("South", "K3")}  # fmt: skip
    assert result.as_of_week == AS_OF


def test_rows_run_from_the_widest_gap_to_the_narrowest() -> None:
    assert [(g.region, g.sku_id) for g in gaps().gaps] == [
        ("North", "N1"),
        ("South", "K3"),
        ("North", "K2"),
        ("North", "K1"),
        ("South", "K1"),
    ]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"regions": [Region.SOUTH]}, {("South", "K1"), ("South", "K3")}),
        ({"categories": ["Snacks"]}, {("North", "N1")}),
        ({"sku_ids": ["K1"]}, {("North", "K1"), ("South", "K1")}),
        ({"kvi_only": True}, {("North", "K1"), ("North", "K2"), ("South", "K1"), ("South", "K3")}),
        ({"regions": [Region.NORTH], "kvi_only": True}, {("North", "K1"), ("North", "K2")}),
    ],
)
def test_filters_narrow_the_rows(filters: dict[str, Any], expected: set[tuple[str, str]]) -> None:
    assert {(g.region, g.sku_id) for g in gaps(**filters).gaps} == expected


@pytest.mark.parametrize(
    ("filters", "unknown"),
    [({"sku_ids": ["K1", "NOPE"]}, "NOPE"), ({"categories": ["Toys"]}, "Toys")],
)
def test_unknown_skus_or_categories_are_rejected(filters: dict[str, Any], unknown: str) -> None:
    with pytest.raises(ValueError, match=unknown):
        gaps(**filters)


def test_no_prices_before_the_as_of_week_gives_no_rows() -> None:
    assert competitor_gaps(PRODUCTS, PRICES, as_of_week=0, policy=POLICY).gaps == ()


# The KVI tolerance helper for the optimiser: one-sided, on the effective unit price.


def line(sku_id: str, /, **changes: Any) -> PlanLine:
    fields: dict[str, Any] = {
        "sku_id": sku_id,
        "region": "North",
        "mechanism": "PCT_OFF",
        "depth_pct": 5,
        "duration_weeks": 2,
        "start_week": AS_OF + 1,
        "target_segment": "All customers",
    }
    return PlanLine.model_validate(fields | changes)


def tolerant(result: CompetitorGaps, promo: PlanLine) -> bool:
    return result.within_kvi_tolerance(promo)


def test_a_kvi_promo_price_within_tolerance_above_the_competitor_passes() -> None:
    # K2 North: competitor ₹94.90, so the ceiling is ₹96.80 at the default 2% tolerance.
    assert tolerant(gaps(), line("K2", depth_pct=4)) is True  # ₹96
    assert tolerant(gaps(), line("K2", depth_pct=3)) is False  # ₹97


def test_pricing_below_the_competitor_always_passes() -> None:
    assert tolerant(gaps(), line("K2", depth_pct=40)) is True
    assert tolerant(gaps(), line("K2", mechanism="BOGO", depth_pct=50)) is True


def test_the_tolerance_uses_the_mechanisms_effective_unit_price() -> None:
    # K3 South: competitor ₹180, ceiling ₹183.60. FIXED_PRICE at 8% is ₹184 → charm ₹179.
    assert tolerant(gaps(), line("K3", region="South", depth_pct=8)) is False  # ₹184
    assert tolerant(gaps(), line("K3", region="South", mechanism="FIXED_PRICE", depth_pct=8))


def test_a_bundle_checks_both_skus() -> None:
    # K1 North: competitor ₹95.10, ceiling ₹97.00. K2 North ceiling ₹96.80.
    both_fine = line("K1", mechanism="BUNDLE", bundle_partner_sku_id="K2", depth_pct=4)
    partner_too_dear = line("K1", mechanism="BUNDLE", bundle_partner_sku_id="K2", depth_pct=3)

    assert tolerant(gaps(), both_fine) is True
    assert tolerant(gaps(), partner_too_dear) is False


def test_non_kvis_and_kvis_without_a_known_competitor_price_always_pass() -> None:
    assert tolerant(gaps(), line("N1", depth_pct=1)) is True
    assert tolerant(gaps(), line("K3", depth_pct=1)) is True  # no North price for K3


def test_the_tolerance_comes_from_company_policy() -> None:
    loose = competitor_gaps(
        PRODUCTS, PRICES, as_of_week=AS_OF, policy=CompanyPolicy(kvi_price_tolerance=0.05)
    )

    assert loose.kvi_price_tolerance == 0.05
    assert tolerant(loose, line("K2", depth_pct=1)) is True  # ₹99 ≤ ₹99.645
