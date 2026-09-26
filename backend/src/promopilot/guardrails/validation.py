"""Deterministic plan validation: every hard constraint on plan-time values (ADR 0012, 0028)."""

from collections import Counter, defaultdict
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, PlanningRequest, Region
from promopilot.economics import blended_margin, effective_unit_price

ONE_PAISA = 0.01
_EPSILON = 1e-9


class SkuFacts(BaseModel):
    """What validation needs to know about one SKU of a plan line, in its region."""

    model_config = ConfigDict(frozen=True)

    category: str
    base_price: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    overstocked: bool
    """Overstocked in the line's region: it may then sell below unit cost (ADR 0007)."""


class LineFacts(BaseModel):
    """A plan line with the plan-time numbers the planning tools computed for it (rupees).

    Units and stock refer to the anchor SKU; revenue, gross profit and promo cost include a
    BUNDLE's partner (ADR 0017).
    """

    model_config = ConfigDict(frozen=True)

    line: PlanLine
    anchor: SkuFacts
    partner: SkuFacts | None = None
    expected_units: float = Field(ge=0)
    p90_units: float = Field(ge=0)
    available_stock: float
    """Pooled across the region's stores: sum of on hand minus safety stock (ADR 0004)."""
    expected_revenue: float = Field(ge=0)
    expected_gross_profit: float
    promo_cost: float = Field(ge=0)

    @model_validator(mode="after")
    def _partner_facts_for_a_bundle(self) -> Self:
        if (self.partner is None) != (self.line.bundle_partner_sku_id is None):
            raise ValueError("partner facts are required for a BUNDLE line and only for one")
        return self


class PlanFacts(BaseModel):
    """A plan under validation. Unlike `PromoPlan` it may hold two lines for one SKU in one
    region, so that validation can report it instead of failing to build the plan."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[LineFacts, ...]


class ViolationCode(StrEnum):
    BUDGET = "BUDGET"
    MIN_MARGIN = "MIN_MARGIN"
    MARGIN_FLOOR = "MARGIN_FLOOR"
    STOCK = "STOCK"
    MAX_DISCOUNT = "MAX_DISCOUNT"
    BELOW_COST = "BELOW_COST"
    WINDOW = "WINDOW"
    MAX_SKUS = "MAX_SKUS"
    DUPLICATE_LINE = "DUPLICATE_LINE"


class Violation(BaseModel):
    """One broken hard constraint, specific enough for the planner to fix."""

    model_config = ConfigDict(frozen=True)

    code: ViolationCode
    message: str
    sku_id: str | None = None
    region: Region | None = None
    actual: float | None = None
    limit: float | None = None


def validate_plan(
    plan: PlanFacts, request: PlanningRequest, policy: CompanyPolicy
) -> tuple[Violation, ...]:
    """Every hard-constraint violation of a plan on its own plan-time numbers; () if none.

    Plan-level violations (budget, margins) come first, then per-line ones in line order,
    then max promoted SKUs and duplicate lines.
    """
    violations = [*_budget(plan, request), *_margins(plan, request, policy)]
    for fact in plan.lines:
        violations += _stock(fact)
        violations += _discount_and_cost(fact, policy)
        violations += _window(fact, request)
    violations += _max_skus(plan, policy)
    violations += _duplicates(plan)
    return tuple(violations)


def _budget(plan: PlanFacts, request: PlanningRequest) -> list[Violation]:
    total = sum(fact.promo_cost for fact in plan.lines)
    if round(total - request.marketing_budget, 6) <= ONE_PAISA:
        return []
    return [
        Violation(
            code=ViolationCode.BUDGET,
            message=(
                f"total promo cost {_rupees(total)} exceeds the marketing budget "
                f"{_rupees(request.marketing_budget)}"
            ),
            actual=total,
            limit=request.marketing_budget,
        )
    ]


def _margins(plan: PlanFacts, request: PlanningRequest, policy: CompanyPolicy) -> list[Violation]:
    blended = blended_margin(
        [fact.expected_revenue for fact in plan.lines],
        [fact.expected_gross_profit for fact in plan.lines],
    )
    if blended is None:
        return []
    limits = [(ViolationCode.MIN_MARGIN, "minimum margin", request.min_margin)]
    limits.append((ViolationCode.MARGIN_FLOOR, "company-policy margin floor", policy.margin_floor))
    return [
        Violation(
            code=code,
            message=f"blended expected margin {blended:.1%} is below the {name} {limit:.1%}",
            actual=blended,
            limit=limit,
        )
        for code, name, limit in limits
        if limit is not None and blended < limit - _EPSILON
    ]


def _stock(fact: LineFacts) -> list[Violation]:
    if fact.p90_units <= fact.available_stock + _EPSILON:
        return []
    line = fact.line
    return [
        Violation(
            code=ViolationCode.STOCK,
            message=(
                f"{line.sku_id} in {line.region}: P90 units {fact.p90_units:,.0f} exceed "
                f"available stock {fact.available_stock:,.0f}"
            ),
            sku_id=line.sku_id,
            region=line.region,
            actual=fact.p90_units,
            limit=fact.available_stock,
        )
    ]


def _discount_and_cost(fact: LineFacts, policy: CompanyPolicy) -> list[Violation]:
    line = fact.line
    violations: list[Violation] = []
    anchor_price = effective_unit_price(line.mechanism, fact.anchor.base_price, line.depth_pct)
    discount = 1 - anchor_price / fact.anchor.base_price
    max_discount = policy.max_discount_pct / 100
    if discount > max_discount + _EPSILON:
        violations.append(
            Violation(
                code=ViolationCode.MAX_DISCOUNT,
                message=(
                    f"{line.sku_id} in {line.region}: effective discount {discount:.0%} is "
                    f"deeper than the company-policy maximum {max_discount:.0%}"
                ),
                sku_id=line.sku_id,
                region=line.region,
                actual=discount,
                limit=max_discount,
            )
        )
    priced = [(line.sku_id, fact.anchor, anchor_price)]
    if fact.partner is not None and line.bundle_partner_sku_id is not None:
        partner_price = effective_unit_price(
            Mechanism.BUNDLE, fact.partner.base_price, line.depth_pct
        )
        priced.append((line.bundle_partner_sku_id, fact.partner, partner_price))
    for sku_id, sku, price in priced:
        if price < sku.unit_cost - _EPSILON and not sku.overstocked:
            violations.append(
                Violation(
                    code=ViolationCode.BELOW_COST,
                    message=(
                        f"{sku_id} in {line.region} sells at {_rupees(price)}, below its unit "
                        f"cost {_rupees(sku.unit_cost)}, and is not overstocked"
                    ),
                    sku_id=sku_id,
                    region=line.region,
                    actual=price,
                    limit=sku.unit_cost,
                )
            )
    return violations


def _window(fact: LineFacts, request: PlanningRequest) -> list[Violation]:
    line = fact.line
    window = request.promo_window
    end_week = line.start_week + line.duration_weeks - 1
    if window.start_week <= line.start_week and end_week <= window.end_week:
        return []
    return [
        Violation(
            code=ViolationCode.WINDOW,
            message=(
                f"{line.sku_id} in {line.region} runs weeks {line.start_week}-{end_week}, "
                f"outside the promo window {window.start_week}-{window.end_week}"
            ),
            sku_id=line.sku_id,
            region=line.region,
        )
    ]


def _max_skus(plan: PlanFacts, policy: CompanyPolicy) -> list[Violation]:
    # A BUNDLE partner is promoted too, so it counts in its own category (ADR 0028).
    promoted: defaultdict[tuple[str, Region], set[str]] = defaultdict(set)
    for fact in plan.lines:
        region = fact.line.region
        promoted[(fact.anchor.category, region)].add(fact.line.sku_id)
        if fact.partner is not None and fact.line.bundle_partner_sku_id is not None:
            promoted[(fact.partner.category, region)].add(fact.line.bundle_partner_sku_id)
    limit = policy.max_promoted_skus_per_category_per_region
    return [
        Violation(
            code=ViolationCode.MAX_SKUS,
            message=(
                f"{len(skus)} {category} SKUs are promoted in {region}; company policy allows "
                f"at most {limit} per category per region"
            ),
            region=region,
            actual=len(skus),
            limit=limit,
        )
        for (category, region), skus in promoted.items()
        if len(skus) > limit
    ]


def _duplicates(plan: PlanFacts) -> list[Violation]:
    # A BUNDLE partner is locked: it occupies its region like an anchor (ADR 0014).
    occupied = Counter(
        (sku_id, fact.line.region) for fact in plan.lines for sku_id in fact.line.skus
    )
    return [
        Violation(
            code=ViolationCode.DUPLICATE_LINE,
            message=(
                f"{sku_id} is in {count} plan lines in {region}; a plan has at most one plan "
                f"line per SKU per region"
            ),
            sku_id=sku_id,
            region=region,
            actual=count,
            limit=1,
        )
        for (sku_id, region), count in occupied.items()
        if count > 1
    ]


def _rupees(amount: float) -> str:
    """₹ with Indian digit grouping (₹1,50,000); paise only when there are any."""
    paise = round(abs(amount) * 100)
    whole, fraction = divmod(paise, 100)
    digits = str(whole)
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail])
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{grouped}" + (f".{fraction:02d}" if fraction else "")
