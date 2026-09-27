"""`plan_limits`: a brief may tighten company policy but never loosen it (ADR 0007, ADR 0040)."""

from typing import Any

import pytest

from promopilot.domain import (
    CompanyPolicy,
    ConstraintSource,
    PlanningRequest,
    PolicyFinding,
    PromoWindow,
    Region,
    Scope,
)
from promopilot.guardrails import plan_limits

POLICY = CompanyPolicy()


def request(**changes: Any) -> PlanningRequest:
    fields: dict[str, Any] = {
        "as_of_week": 104,
        "scope": Scope(regions=(Region.NORTH,), categories=("Snacks",)),
        "promo_window": PromoWindow(start_week=108, end_week=109),
        "marketing_budget": 200_000.0,
    }
    return PlanningRequest.model_validate(fields | changes)


def test_without_brief_values_company_policy_applies_and_nothing_is_flagged() -> None:
    limits = plan_limits(request(), POLICY)

    assert limits.min_margin == 0.15
    assert limits.min_margin_source is ConstraintSource.COMPANY_POLICY
    assert limits.max_promoted_skus == 10
    assert limits.max_promoted_skus_source is ConstraintSource.COMPANY_POLICY
    assert limits.kvi_price_tolerance is None
    assert limits.findings == ()


def test_a_brief_may_tighten_every_policy_rule_it_can_set() -> None:
    limits = plan_limits(
        request(
            min_margin=0.22, max_promoted_skus_per_category_per_region=4, kvi_price_tolerance=0.01
        ),
        POLICY,
    )

    assert (limits.min_margin, limits.min_margin_source) == (0.22, ConstraintSource.BRIEF)
    assert (limits.max_promoted_skus, limits.max_promoted_skus_source) == (
        4,
        ConstraintSource.BRIEF,
    )
    assert (limits.kvi_price_tolerance, limits.kvi_price_tolerance_source) == (
        0.01,
        ConstraintSource.BRIEF,
    )
    assert limits.findings == ()


def test_the_brief_enables_the_kvi_tolerance_at_the_policy_tolerance() -> None:
    limits = plan_limits(request(kvi_price_tolerance=0.02), POLICY)

    assert (limits.kvi_price_tolerance, limits.kvi_price_tolerance_source) == (
        0.02,
        ConstraintSource.BRIEF,
    )


def test_a_policy_that_enables_the_kvi_tolerance_applies_it_without_the_brief() -> None:
    limits = plan_limits(request(), CompanyPolicy(kvi_price_tolerance_enabled=True))

    assert (limits.kvi_price_tolerance, limits.kvi_price_tolerance_source) == (
        0.02,
        ConstraintSource.COMPANY_POLICY,
    )


@pytest.mark.parametrize(
    ("changes", "field", "requested", "applied"),
    [
        ({"min_margin": 0.12}, "min_margin", 0.12, 0.15),
        (
            {"max_promoted_skus_per_category_per_region": 12},
            "max_promoted_skus_per_category_per_region",
            12,
            10,
        ),
        ({"kvi_price_tolerance": 0.05}, "kvi_price_tolerance", 0.05, 0.02),
    ],
)
def test_a_brief_value_that_would_loosen_policy_keeps_the_policy_value_and_is_flagged(
    changes: dict[str, Any], field: str, requested: float, applied: float
) -> None:
    limits = plan_limits(request(**changes), POLICY)

    (finding,) = limits.findings
    assert isinstance(finding, PolicyFinding)
    assert (finding.field, finding.requested, finding.applied) == (field, requested, applied)
    assert "company policy" in finding.message
    assert limits.min_margin >= POLICY.margin_floor
    assert limits.max_promoted_skus <= POLICY.max_promoted_skus_per_category_per_region
    assert limits.kvi_price_tolerance in (None, POLICY.kvi_price_tolerance)
    if field == "kvi_price_tolerance":
        assert limits.kvi_price_tolerance_source is ConstraintSource.COMPANY_POLICY
