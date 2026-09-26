import pytest
from pydantic import ValidationError

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PromoPlan,
    Region,
    TargetSegment,
)


def line(
    sku_id: str = "SKU001",
    region: Region = Region.NORTH,
    mechanism: Mechanism = Mechanism.PCT_OFF,
    depth_pct: int = 20,
    bundle_partner_sku_id: str | None = None,
) -> PlanLine:
    return PlanLine(
        sku_id=sku_id,
        region=region,
        mechanism=mechanism,
        depth_pct=depth_pct,
        duration_weeks=2,
        start_week=105,
        target_segment=TargetSegment.ALL_CUSTOMERS,
        bundle_partner_sku_id=bundle_partner_sku_id,
    )


def test_promo_plan_rejects_two_plan_lines_for_the_same_sku_in_the_same_region() -> None:
    with pytest.raises(ValidationError, match="one plan line per SKU per region"):
        PromoPlan(lines=(line(depth_pct=20), line(depth_pct=30)))


def test_promo_plan_allows_the_same_sku_in_different_regions() -> None:
    plan = PromoPlan(lines=(line(region=Region.NORTH), line(region=Region.WEST, depth_pct=30)))

    assert len(plan.lines) == 2


def test_bundle_plan_line_requires_a_partner_sku() -> None:
    with pytest.raises(ValidationError, match="BUNDLE needs a bundle partner"):
        line(mechanism=Mechanism.BUNDLE)


def test_only_a_bundle_plan_line_may_name_a_partner_sku() -> None:
    with pytest.raises(ValidationError, match="only a BUNDLE"):
        line(mechanism=Mechanism.PCT_OFF, bundle_partner_sku_id="SKU002")


def test_bundle_partner_cannot_be_its_own_anchor() -> None:
    with pytest.raises(ValidationError, match="its own partner"):
        line(mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU001")


def test_bogo_plan_line_is_always_fifty_percent_deep() -> None:
    with pytest.raises(ValidationError, match="BOGO"):
        line(mechanism=Mechanism.BOGO, depth_pct=30)


def test_bundle_partner_cannot_have_its_own_plan_line_in_the_same_region() -> None:
    bundle = line(sku_id="SKU001", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU002")

    with pytest.raises(ValidationError, match="one plan line per SKU per region"):
        PromoPlan(lines=(bundle, line(sku_id="SKU002")))


def test_bundle_partner_may_have_its_own_plan_line_in_another_region() -> None:
    bundle = line(sku_id="SKU001", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU002")

    plan = PromoPlan(lines=(bundle, line(sku_id="SKU002", region=Region.SOUTH)))

    assert len(plan.lines) == 2


def test_company_policy_defaults_are_the_adr_0007_table() -> None:
    policy = CompanyPolicy()

    assert policy.margin_floor == 0.15
    assert policy.max_discount_pct == 50
    assert policy.undercut_threshold == 0.05
    assert policy.kvi_price_tolerance == 0.02
    assert policy.kvi_price_tolerance_enabled is False
    assert policy.overstock_threshold_weeks == 8
    assert policy.write_off_rate == 0.30
    assert policy.fixed_cost_per_line_week == {
        Mechanism.PCT_OFF: 500.0,
        Mechanism.FIXED_PRICE: 500.0,
        Mechanism.BOGO: 750.0,
        Mechanism.BUNDLE: 1000.0,
    }
    assert policy.max_promoted_skus_per_category_per_region == 10


def test_company_policy_is_immutable() -> None:
    policy = CompanyPolicy()

    with pytest.raises(ValidationError):
        policy.margin_floor = 0.10  # type: ignore[misc]
