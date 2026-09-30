"""Deterministic plan validation: every hard constraint on plan-time values (ADR 0012, 0028),
with the safety margin the plan was made with (ADR 0080)."""

from collections import Counter, defaultdict
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    Region,
    SafetyMargin,
    TargetSegment,
    Violation,
    ViolationCode,
)
from promopilot.economics import blended_margin, effective_unit_price
from promopilot.guardrails.formatting import format_percentile
from promopilot.guardrails.limits import plan_limits
from promopilot.guardrails.safety import (
    budget_z,
    margin_z,
    planned_margin,
    planned_promo_cost,
    stock_units,
    units_cv,
)

ONE_PAISA = 0.01
_EPSILON = 1e-9


class SkuFacts(BaseModel):
    """What validation needs to know about one SKU of a plan line, in its region."""

    model_config = ConfigDict(frozen=True)

    category: str
    base_price: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    overstocked: bool
    """Overstocked in the line's region by days of cover: it may then sell below unit cost
    (ADR 0007). A SKU the brief names for clearance is overstocked too (ADR 0040)."""
    is_kvi: bool = False
    competitor_price: float | None = None
    """The competitor's latest price in the line's region (ADR 0031), if known."""


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
    units_std: float = Field(default=0.0, ge=0)
    """The std of the anchor's units, as the demand model predicts it (ADR 0024)."""
    promo_cost_std: float = Field(default=0.0, ge=0)
    """The std of the promo cost: discount funding moves with units (ADR 0080)."""

    @model_validator(mode="after")
    def _partner_facts_for_a_bundle(self) -> Self:
        if (self.partner is None) != (self.line.bundle_partner_sku_id is None):
            raise ValueError("partner facts are required for a BUNDLE line and only for one")
        return self


class ClearanceFacts(BaseModel):
    """What the plan is expected to sell of a SKU with a clearance target, in one region."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    region: Region
    available_stock: float = Field(gt=0)
    expected_units: float
    """Expected units sold over the promo window, the plan's promotions included (ADR
    0040)."""


class SubstituteFacts(BaseModel):
    """Two SKUs the relations model detects as substitutes, with its estimated cross-price
    effect θ (one symmetric θ per pair, ADR 0029)."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    other_sku_id: str
    theta: float


class PlanFacts(BaseModel):
    """A plan under validation. Unlike `PromoPlan` it may hold two lines for one SKU in one
    region, so that validation can report it instead of failing to build the plan."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[LineFacts, ...]
    clearance: tuple[ClearanceFacts, ...] = ()
    """One per SKU with a clearance target and region with available stock."""
    substitutes: tuple[SubstituteFacts, ...] = ()
    """The detected substitute pairs among the plan's SKUs (ADR 0075)."""
    safety: SafetyMargin = SafetyMargin()
    """The safety margin the plan was made with: its budget, stock and margin are checked at
    it (ADR 0080). The default checks expected values and P90 units."""


def run_together(line: PlanLine, other: PlanLine) -> bool:
    """Whether two plan lines run together: in one region, with a promo week and a target
    segment in common. All customers shares every segment (ADR 0033, ADR 0075)."""
    if line.region is not other.region:
        return False
    if line.start_week + line.duration_weeks <= other.start_week:
        return False
    if other.start_week + other.duration_weeks <= line.start_week:
        return False
    everyone = TargetSegment.ALL_CUSTOMERS
    return everyone in (line.target_segment, other.target_segment) or (
        line.target_segment is other.target_segment
    )


def validate_plan(
    plan: PlanFacts, request: PlanningRequest, policy: CompanyPolicy
) -> tuple[Violation, ...]:
    """Every hard-constraint violation of a plan on its own plan-time numbers; () if none.

    Plan-level violations (budget, regional caps, margins) come first, then per-line ones in
    line order, then max promoted SKUs, duplicate lines, clearance targets and strong
    substitutes promoted together. The brief may only tighten company policy (`plan_limits`,
    ADR 0007). The budget, stock and margin are checked at the plan's safety margin (ADR
    0080), as the optimiser planned them.
    """
    limits = plan_limits(request, policy)
    cleared = {target.sku_id for target in request.clearance_targets}
    violations = [
        *_budget(plan, request),
        *_regional_budgets(plan, request),
        *_margins(plan, request, policy),
    ]
    for fact in plan.lines:
        violations += _stock(fact, plan.safety)
        violations += _discount_and_cost(fact, policy, cleared)
        violations += _window(fact, request)
        violations += _kvi_tolerance(fact, limits.kvi_price_tolerance)
    violations += _max_skus(plan, limits.max_promoted_skus)
    violations += _duplicates(plan)
    violations += _clearance(plan, request)
    violations += _strong_substitutes(plan, policy)
    return tuple(violations)


def _costs(plan: PlanFacts) -> list[float]:
    """Each line's promo cost at the plan's budget quantile (ADR 0080)."""
    if not plan.lines:
        return []
    costs = planned_promo_cost(
        np.array([fact.promo_cost for fact in plan.lines]),
        np.array([fact.promo_cost_std for fact in plan.lines]),
        plan.safety,
    )
    return [float(cost) for cost in costs]


def _cost_name(plan: PlanFacts) -> str:
    if budget_z(plan.safety) <= 0:
        return "promo cost"
    return f"{format_percentile(plan.safety.budget_quantile)} promo cost"


def _budget(plan: PlanFacts, request: PlanningRequest) -> list[Violation]:
    total = sum(_costs(plan))
    if round(total - request.marketing_budget, 6) <= ONE_PAISA:
        return []
    return [
        Violation(
            code=ViolationCode.BUDGET,
            message=(
                f"total {_cost_name(plan)} {_rupees(total)} exceeds the marketing budget "
                f"{_rupees(request.marketing_budget)}"
            ),
            actual=total,
            limit=request.marketing_budget,
        )
    ]


def _regional_budgets(plan: PlanFacts, request: PlanningRequest) -> list[Violation]:
    spent: defaultdict[Region, float] = defaultdict(float)
    for fact, cost in zip(plan.lines, _costs(plan), strict=True):
        spent[fact.line.region] += cost
    return [
        Violation(
            code=ViolationCode.REGIONAL_BUDGET,
            message=(
                f"{_cost_name(plan)} in {region} {_rupees(spent[region])} exceeds the brief's "
                f"regional budget cap {_rupees(cap)}"
            ),
            region=region,
            actual=spent[region],
            limit=cap,
        )
        for region, cap in request.regional_budget_caps.items()
        if round(spent[region] - cap, 6) > ONE_PAISA
    ]


def _margins(plan: PlanFacts, request: PlanningRequest, policy: CompanyPolicy) -> list[Violation]:
    revenue = [fact.expected_revenue for fact in plan.lines]
    profit = [fact.expected_gross_profit for fact in plan.lines]
    what = "blended expected margin"
    if margin_z(plan.safety) > 0 and plan.lines:
        # The least blend with each line's units within the margin quantile (ADR 0080).
        cv = units_cv(
            np.array([fact.expected_units for fact in plan.lines]),
            np.array([fact.units_std for fact in plan.lines]),
        )
        blended = planned_margin(np.array(revenue), np.array(profit), cv, plan.safety)
        what = f"blended margin at its {format_percentile(plan.safety.margin_quantile)}"
    else:
        blended = blended_margin(revenue, profit)
    if blended is None:
        return []
    limits = [(ViolationCode.MIN_MARGIN, "minimum margin", request.min_margin)]
    limits.append((ViolationCode.MARGIN_FLOOR, "company-policy margin floor", policy.margin_floor))
    return [
        Violation(
            code=code,
            message=f"{what} {blended:.1%} is below the {name} {limit:.1%}",
            actual=blended,
            limit=limit,
        )
        for code, name, limit in limits
        if limit is not None and blended < limit - _EPSILON
    ]


def _stock(fact: LineFacts, safety: SafetyMargin) -> list[Violation]:
    """P90 units, or with a stock buffer the expected units plus its standard deviations,
    whichever is more, within available stock (ADR 0004, ADR 0080)."""
    buffered = stock_units(np.array([fact.expected_units]), np.array([fact.units_std]), safety)
    units, name = fact.p90_units, "P90 units"
    if fact.units_std > 0 and float(buffered[0]) > fact.p90_units:
        units, name = float(buffered[0]), f"expected units plus {safety.stock_sigmas:g} std"
    if units <= fact.available_stock + _EPSILON:
        return []
    line = fact.line
    return [
        Violation(
            code=ViolationCode.STOCK,
            message=(
                f"{line.sku_id} in {line.region}: {name} {units:,.0f} exceed "
                f"available stock {fact.available_stock:,.0f}"
            ),
            sku_id=line.sku_id,
            region=line.region,
            actual=units,
            limit=fact.available_stock,
        )
    ]


def _discount_and_cost(
    fact: LineFacts, policy: CompanyPolicy, cleared: set[str]
) -> list[Violation]:
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
        overstocked = sku.overstocked or sku_id in cleared
        if price < sku.unit_cost - _EPSILON and not overstocked:
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


def _kvi_tolerance(fact: LineFacts, tolerance: float | None) -> list[Violation]:
    """Each KVI the line promotes priced at most the tolerance above the competitor (ADR
    0031); off when the tolerance is None."""
    if tolerance is None:
        return []
    line = fact.line
    skus = [(line.sku_id, fact.anchor)]
    if fact.partner is not None and line.bundle_partner_sku_id is not None:
        skus.append((line.bundle_partner_sku_id, fact.partner))
    violations = []
    for sku_id, sku in skus:
        if not sku.is_kvi or sku.competitor_price is None:
            continue
        price = effective_unit_price(line.mechanism, sku.base_price, line.depth_pct)
        highest = sku.competitor_price * (1 + tolerance)
        if price > highest + _EPSILON:
            violations.append(
                Violation(
                    code=ViolationCode.KVI_TOLERANCE,
                    message=(
                        f"KVI {sku_id} in {line.region} sells at {_rupees(price)}, more than "
                        f"{tolerance:.1%} above the competitor price "
                        f"{_rupees(sku.competitor_price)}"
                    ),
                    sku_id=sku_id,
                    region=line.region,
                    actual=price,
                    limit=highest,
                )
            )
    return violations


def _max_skus(plan: PlanFacts, limit: int) -> list[Violation]:
    # A BUNDLE partner is promoted too, so it counts in its own category (ADR 0028).
    promoted: defaultdict[tuple[str, Region], set[str]] = defaultdict(set)
    for fact in plan.lines:
        region = fact.line.region
        promoted[(fact.anchor.category, region)].add(fact.line.sku_id)
        if fact.partner is not None and fact.line.bundle_partner_sku_id is not None:
            promoted[(fact.partner.category, region)].add(fact.line.bundle_partner_sku_id)
    return [
        Violation(
            code=ViolationCode.MAX_SKUS,
            message=(
                f"{len(skus)} {category} SKUs are promoted in {region}; at most {limit} are "
                f"allowed per category per region"
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


def _clearance(plan: PlanFacts, request: PlanningRequest) -> list[Violation]:
    targets = {target.sku_id: target.sell_through for target in request.clearance_targets}
    violations = []
    for fact in plan.clearance:
        target = targets.get(fact.sku_id)
        if target is None:
            continue
        sell_through = fact.expected_units / fact.available_stock
        if sell_through >= target - _EPSILON:
            continue
        short = target * fact.available_stock - fact.expected_units
        violations.append(
            Violation(
                code=ViolationCode.CLEARANCE_TARGET,
                message=(
                    f"{fact.sku_id} in {fact.region} is expected to sell through "
                    f"{sell_through:.1%} of its stock, below the clearance target "
                    f"{target:.1%}: short by {short:,.0f} units"
                ),
                sku_id=fact.sku_id,
                region=fact.region,
                actual=sell_through,
                limit=target,
            )
        )
    return violations


def _strong_substitutes(plan: PlanFacts, policy: CompanyPolicy) -> list[Violation]:
    """Each pair of strong substitutes promoted together, once per region: by two lines that
    run together, or by one BUNDLE (ADR 0075)."""
    least = policy.strong_substitute_min_theta
    strong = {
        frozenset((pair.sku_id, pair.other_sku_id)): pair.theta
        for pair in plan.substitutes
        if pair.theta >= least - _EPSILON
    }
    found: dict[tuple[frozenset[str], Region], None] = {}
    lines = [fact.line for fact in plan.lines]
    for n, line in enumerate(lines):
        for other in lines[n:]:
            if other is not line and not run_together(line, other):
                continue
            for sku_id in line.skus:
                for other_sku_id in other.skus:
                    pair = frozenset((sku_id, other_sku_id))
                    if pair in strong:
                        found[(pair, line.region)] = None
    violations = []
    for pair, region in found:
        first, second = sorted(pair)
        theta = strong[pair]
        violations.append(
            Violation(
                code=ViolationCode.STRONG_SUBSTITUTES,
                message=(
                    f"{first} and {second} are strong substitutes (estimated θ {theta:.2f}, "
                    f"at least {least:.2f}) promoted together in {region}: promote one of "
                    "them, or run them in different weeks or segments"
                ),
                sku_id=first,
                region=region,
                actual=theta,
                limit=least,
            )
        )
    return violations


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
