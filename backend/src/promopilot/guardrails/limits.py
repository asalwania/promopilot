"""The company-policy rules a planning request plans under, tightened by the brief (ADR 0007).

A brief may tighten company policy but never loosen it. Where a brief value would loosen it
(a minimum margin below the margin floor, a promoted-SKU cap above policy's, a KVI price
tolerance wider than policy's), the policy value applies and the value is flagged as a
`PolicyFinding` for the manager (ADR 0040). The optimiser and plan validation both read the
rules from here, so they can never disagree.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from promopilot.domain import (
    CompanyPolicy,
    ConstraintSource,
    PlanLine,
    PlanningRequest,
    PolicyFinding,
)


@dataclass(frozen=True)
class PlanLimits:
    """The rules applied, and who set each one."""

    min_margin: float
    """The minimum blended margin: the brief's, never below the margin floor."""
    min_margin_source: ConstraintSource
    max_promoted_skus: int
    """Per category per region: policy's, or the brief's where it is tighter."""
    max_promoted_skus_source: ConstraintSource
    kvi_price_tolerance: float | None
    """How far above the competitor price a KVI promo price may sit; None when the rule is
    off (ADR 0031)."""
    kvi_price_tolerance_source: ConstraintSource
    findings: tuple[PolicyFinding, ...]
    """Brief values that would have loosened company policy."""


def plan_limits(request: PlanningRequest, policy: CompanyPolicy) -> PlanLimits:
    """The rules `request` is planned under, and the brief values that were not applied."""
    findings: list[PolicyFinding] = []

    minimum, margin_source = policy.margin_floor, ConstraintSource.COMPANY_POLICY
    if request.min_margin is not None:
        if request.min_margin > policy.margin_floor:
            minimum, margin_source = request.min_margin, ConstraintSource.BRIEF
        elif request.min_margin < policy.margin_floor:
            findings.append(
                _finding(
                    "min_margin",
                    request.min_margin,
                    policy.margin_floor,
                    f"the brief's minimum margin {request.min_margin:.1%} is below the "
                    f"company-policy margin floor {policy.margin_floor:.1%}",
                )
            )

    cap = policy.max_promoted_skus_per_category_per_region
    cap_source = ConstraintSource.COMPANY_POLICY
    wanted = request.max_promoted_skus_per_category_per_region
    if wanted is not None:
        if wanted < cap:
            cap, cap_source = wanted, ConstraintSource.BRIEF
        elif wanted > cap:
            findings.append(
                _finding(
                    "max_promoted_skus_per_category_per_region",
                    wanted,
                    cap,
                    f"the brief allows {wanted} promoted SKUs per category per region, more "
                    f"than the {cap} company policy allows",
                )
            )

    tolerance: float | None = None
    tolerance_source = ConstraintSource.COMPANY_POLICY
    if policy.kvi_price_tolerance_enabled:
        tolerance = policy.kvi_price_tolerance
    asked = request.kvi_price_tolerance
    if asked is not None:
        if asked > policy.kvi_price_tolerance:
            tolerance = policy.kvi_price_tolerance
            findings.append(
                _finding(
                    "kvi_price_tolerance",
                    asked,
                    policy.kvi_price_tolerance,
                    f"the brief lets KVI promo prices sit {asked:.1%} above the competitor, "
                    f"wider than the {policy.kvi_price_tolerance:.1%} company policy allows",
                )
            )
        elif not policy.kvi_price_tolerance_enabled or asked < policy.kvi_price_tolerance:
            tolerance, tolerance_source = asked, ConstraintSource.BRIEF

    return PlanLimits(
        min_margin=minimum,
        min_margin_source=margin_source,
        max_promoted_skus=cap,
        max_promoted_skus_source=cap_source,
        kvi_price_tolerance=tolerance,
        kvi_price_tolerance_source=tolerance_source,
        findings=tuple(findings),
    )


def _finding(field: str, requested: float, applied: float, reason: str) -> PolicyFinding:
    return PolicyFinding(
        field=field,
        requested=requested,
        applied=applied,
        message=f"{reason}; company policy is kept, since a brief may only tighten it",
    )


def deeper_than_policy(lines: Iterable[PlanLine], policy: CompanyPolicy) -> str | None:
    """Why a plan line an agent asks about is deeper than the company-policy maximum discount,
    or None when none is (ADR 0079).

    The what-if tools (`estimate_demand`, `simulate_plan`) refuse such a line, so no text can
    make them price one. It reads each line's stated depth, which is its discount for every
    mechanism but FIXED_PRICE, whose charm price may sit a few rupees deeper; a plan's own
    lines are checked on their effective prices by `validate_plan`.
    """
    for line in lines:
        if line.depth_pct > policy.max_discount_pct:
            return (
                f"{line.sku_id} in {line.region} is {line.depth_pct}% off, deeper than the "
                f"company-policy maximum discount of {policy.max_discount_pct}%; company "
                "policy binds every plan line"
            )
    return None
