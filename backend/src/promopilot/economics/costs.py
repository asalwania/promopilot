"""Promo cost: discount funding plus fixed marketing cost (ADR 0005)."""

from collections.abc import Mapping
from typing import Any, cast

from promopilot.domain import CompanyPolicy, Mechanism, Segment, TargetSegment
from promopilot.economics.money import Money


def discount_funding(
    base_price: float,
    effective_price: float,
    units_by_segment: Mapping[Segment, Money],
    target_segment: TargetSegment,
) -> Money:
    """(base price - effective price) x the expected units sold to the target segment.

    A segment-exclusive offer funds only its own segment's units (ADR 0006); All customers
    funds every segment's. For a BUNDLE, add the anchor's and the partner's funding.
    """
    if target_segment is TargetSegment.ALL_CUSTOMERS:
        units: Any = sum(units_by_segment.values())
    else:
        units = units_by_segment[Segment(target_segment.value)]
    return cast(Money, (base_price - effective_price) * units)


def fixed_marketing_cost(mechanism: Mechanism, duration_weeks: int, policy: CompanyPolicy) -> float:
    """The mechanism's company-policy fixed cost per plan line per week, over the duration."""
    return policy.fixed_cost_per_line_week[mechanism] * duration_weeks


def promo_cost(
    discount_funding: Money, mechanism: Mechanism, duration_weeks: int, policy: CompanyPolicy
) -> Money:
    """What a plan line spends from the marketing budget."""
    fixed: Any = fixed_marketing_cost(mechanism, duration_weeks, policy)
    return cast(Money, discount_funding + fixed)
