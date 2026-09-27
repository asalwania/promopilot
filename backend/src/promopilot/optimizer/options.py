"""Promo option generation (SPEC §9.3, ADR 0035): every option worth solving over, predicted.

For each (SKU, region) in scope, `generate_options` enumerates mechanism x depth x duration x
start week x target segment:

- depths are mechanism-appropriate (ADR 0005): PCT_OFF and FIXED_PRICE 5-50%, BOGO 50% only,
  BUNDLE 10-25%, and a BUNDLE only with a detected complement as its partner, in scope or not
  (ADR 0014);
- every duration of 1-4 weeks at every start week that keeps the option inside the promo
  window;
- one of the four segments, or All customers (ADR 0006).

Options are pruned before they are predicted when their effective discount is deeper than
the company-policy maximum (ADR 0007, ADR 0015), when the anchor or a BUNDLE partner sells
below unit cost without being overstocked in the region, or when a FIXED_PRICE depth lands on
a charm price a shallower depth already offers. The rest are predicted in one batch, and
pruned again when their P90 units, or a BUNDLE partner's, exceed the pooled available stock
(ADR 0004). Each pruned option counts once, under the first reason it fails.

The survivors carry their predictions, cannibalisation and halo (as if each ran alone, ADR
0033) and clearance value, as the oracle counts it (ADR 0005, ADR 0017). Minimum margin and
the budget are plan-level: the optimiser applies them, not this filter (ADR 0007, ADR 0036).
"""

from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PromoWindow,
    PruneReason,
    Region,
    TargetSegment,
)
from promopilot.economics import clearance_value, effective_unit_price
from promopilot.guardrails import SkuFacts
from promopilot.models.demand import OPTION_COLUMNS, Prediction, PredictionContext
from promopilot.models.relations import (
    LineForecast,
    RelationLookup,
    line_effect_totals,
    pairwise_cannibalisations,
)

P90_Z = 1.2816
"""P90 = mean + 1.2816 x std: the normal approximation to the predicted units (ADR 0035)."""

MAX_DURATION_WEEKS = 4
DEPTHS: Mapping[Mechanism, tuple[int, ...]] = {
    Mechanism.PCT_OFF: (5, 10, 15, 20, 25, 30, 40, 50),
    Mechanism.FIXED_PRICE: (5, 10, 15, 20, 25, 30, 40, 50),
    Mechanism.BOGO: (50,),
    Mechanism.BUNDLE: (10, 15, 20, 25),
}
"""Mechanism-appropriate depth levels (ADR 0005), as the promo history uses them."""

_EPSILON = 1e-9


class OptionForecast(LineForecast, Protocol):
    """What generation, and the optimiser's pairwise terms, need from the demand model
    (`promopilot.models.demand.DemandModel`)."""

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction: ...


@dataclass(frozen=True)
class OptionContext:
    """Everything option generation reads besides the planning request."""

    demand_model: OptionForecast
    relations: RelationLookup
    products: pd.DataFrame
    """sku_id, category, base_price and unit_cost of every SKU, in scope or not."""
    stock: pd.DataFrame
    """sku_id, region, available_stock and is_overstock at the as-of week, pooled per region
    (`get_inventory_status`). A SKU and region with no row has no stock."""
    policy: CompanyPolicy = field(default_factory=CompanyPolicy)
    competitor_prices: Mapping[tuple[Region, str], float] = field(default_factory=dict)
    """Competitor price overrides for the predictions; others are the last known."""


TABLE_COLUMNS = [
    *OPTION_COLUMNS,
    "p90_units",
    "available_stock",
    "partner_p90_units",
    "partner_available_stock",
    "cannibalised_profit",
    "halo_profit",
    "clearance_value",
    "value",
]
"""`PromoOptions.table`: the demand model's OPTION_COLUMNS, then P90 units against stock
(the partner's are 0 without a BUNDLE), the line's cannibalisation, halo and clearance value,
and value = incremental_profit - cannibalised_profit + halo_profit + clearance_value, what
the option is worth if it runs alone. Money in rupees (ADR 0015)."""


@dataclass(frozen=True)
class PromoOptions:
    """The promo options that survived pruning, with their numbers, and what was pruned."""

    lines: tuple[PlanLine, ...]
    table: pd.DataFrame
    """One row per line, in the same order: TABLE_COLUMNS."""
    enumerated: int
    """Every option enumerated, kept or pruned."""
    pruned: Mapping[PruneReason, int]
    """Pruned options per reason, every reason present."""
    pruned_by_mechanism: Mapping[tuple[str, Region, Mechanism], frozenset[PruneReason]] = field(
        default_factory=dict
    )
    """Per anchor SKU, region and mechanism, every reason any of its options was pruned for;
    absent where none was. The mechanism comparator explains an unavailable mechanism with it
    (ADR 0041)."""


class FittedOptionFacts:
    """What the optimiser reads beyond the options' own numbers (`OptionFacts`, ADR 0036),
    from the context the options were generated in: each SKU's category, prices and
    overstock flag, and the pairwise cannibalisation of option pairs on the same models."""

    def __init__(self, context: OptionContext) -> None:
        self._context = context
        self._catalogue = _Catalogue.of(context.products)
        self._stock = _Stock.of(context.stock)
        products = context.products
        self._categories = dict(
            zip(products["sku_id"].astype(str), products["category"].astype(str), strict=True)
        )

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return SkuFacts(
            category=self._categories[sku_id],
            base_price=self._catalogue.base_price[sku_id],
            unit_cost=self._catalogue.unit_cost[sku_id],
            overstocked=self._stock.is_overstocked(sku_id, region),
        )

    def pairwise_cannibalisation(self, pairs: Sequence[tuple[PlanLine, PlanLine]]) -> np.ndarray:
        context = self._context
        return pairwise_cannibalisations(
            pairs,
            context.relations,
            context.demand_model,
            context.products,
            PredictionContext(policy=context.policy, competitor_prices=context.competitor_prices),
        )


def generate_options(
    request: PlanningRequest,
    context: OptionContext,
    *,
    mechanisms: Sequence[Mechanism] | None = None,
    target_segments: Sequence[TargetSegment] | None = None,
    sku_ids: Sequence[str] | None = None,
) -> PromoOptions:
    """The promo options for the planning request's scope and promo window.

    `mechanisms`, `target_segments` and `sku_ids` narrow the enumeration further; a SKU
    outside the request's scope is a ValueError, as is an option the demand model cannot
    predict.
    """
    catalogue = _Catalogue.of(context.products)
    stock = _Stock.of(context.stock)
    timings = _timings(request.promo_window)
    targets = [
        target for target in TargetSegment if target_segments is None or target in target_segments
    ]
    chosen = [mechanism for mechanism in Mechanism if mechanisms is None or mechanism in mechanisms]
    per_price = len(timings) * len(targets)

    pruned: Counter[PruneReason] = Counter()
    pruned_by: defaultdict[tuple[str, Region, Mechanism], set[PruneReason]] = defaultdict(set)
    enumerated = 0
    lines: list[PlanLine] = []
    for sku_id in _in_scope(context.products, request, sku_ids):
        partners = _partners(sku_id, context.relations, catalogue)
        for region in request.scope.regions:
            charm_prices: set[float] = set()
            for mechanism, partner, depth in _price_levels(chosen, partners):
                enumerated += per_price
                reason = _price_reason(
                    sku_id, partner, region, mechanism, depth, catalogue, stock, context.policy
                )
                if reason is None and mechanism is Mechanism.FIXED_PRICE:
                    price = effective_unit_price(mechanism, catalogue.base_price[sku_id], depth)
                    if price in charm_prices:
                        reason = PruneReason.DUPLICATE_PRICE
                    charm_prices.add(price)
                if reason is not None:
                    pruned[reason] += per_price
                    pruned_by[sku_id, region, mechanism].add(reason)
                    continue
                lines += [
                    PlanLine(
                        sku_id=sku_id,
                        region=region,
                        mechanism=mechanism,
                        depth_pct=depth,
                        duration_weeks=duration,
                        start_week=start,
                        target_segment=target,
                        bundle_partner_sku_id=partner,
                    )
                    for start, duration in timings
                    for target in targets
                ]

    if not lines:
        return PromoOptions(
            (),
            pd.DataFrame(columns=TABLE_COLUMNS),
            enumerated,
            _counts(pruned),
            _frozen(pruned_by),
        )
    prediction = context.demand_model.predict(
        lines, PredictionContext(policy=context.policy, competitor_prices=context.competitor_prices)
    )
    table = prediction.options.reset_index(drop=True)
    table["p90_units"] = table["units"] + P90_Z * table["units_std"]
    table["available_stock"] = [stock.available(line.sku_id, line.region) for line in lines]
    table["partner_p90_units"] = table["partner_units"] + P90_Z * table["partner_units_std"]
    table["partner_available_stock"] = [
        stock.available(line.bundle_partner_sku_id, line.region) for line in lines
    ]
    over = (table["p90_units"] > table["available_stock"] + _EPSILON).to_numpy()
    partner_over = (
        ~over
        & (table["partner_p90_units"] > table["partner_available_stock"] + _EPSILON).to_numpy()
    )
    pruned[PruneReason.STOCK] += int(over.sum())
    pruned[PruneReason.PARTNER_STOCK] += int(partner_over.sum())
    for n in np.flatnonzero(over | partner_over):
        line = lines[n]
        reason = PruneReason.STOCK if over[n] else PruneReason.PARTNER_STOCK
        pruned_by[line.sku_id, line.region, line.mechanism].add(reason)
    keep = ~(over | partner_over)
    kept = [line for line, fits in zip(lines, keep, strict=True) if fits]
    table = table[keep].reset_index(drop=True)

    effects = line_effect_totals(kept, context.relations, context.demand_model, context.products)
    table["cannibalised_profit"] = effects["cannibalised_profit"].to_numpy()
    table["halo_profit"] = effects["halo_profit"].to_numpy()
    table["clearance_value"] = _clearance(kept, table, catalogue, stock, context.policy)
    table["value"] = (
        table["incremental_profit"]
        - table["cannibalised_profit"]
        + table["halo_profit"]
        + table["clearance_value"]
    )
    return PromoOptions(
        tuple(kept), table[TABLE_COLUMNS], enumerated, _counts(pruned), _frozen(pruned_by)
    )


@dataclass(frozen=True)
class _Catalogue:
    """Base price and unit cost per SKU, in rupees."""

    base_price: dict[str, float]
    unit_cost: dict[str, float]

    @classmethod
    def of(cls, products: pd.DataFrame) -> "_Catalogue":
        sku_ids = [str(sku_id) for sku_id in products["sku_id"]]
        return cls(
            base_price=dict(zip(sku_ids, map(float, products["base_price"]), strict=True)),
            unit_cost=dict(zip(sku_ids, map(float, products["unit_cost"]), strict=True)),
        )


@dataclass(frozen=True)
class _Stock:
    """Pooled available stock and overstock flags per (SKU, region)."""

    available_stock: dict[tuple[str, str], float]
    overstocked: set[tuple[str, str]]

    @classmethod
    def of(cls, stock: pd.DataFrame) -> "_Stock":
        keys = list(zip(stock["sku_id"].astype(str), stock["region"].astype(str), strict=True))
        return cls(
            available_stock=dict(zip(keys, map(float, stock["available_stock"]), strict=True)),
            overstocked={
                key for key, flag in zip(keys, stock["is_overstock"], strict=True) if flag
            },
        )

    def available(self, sku_id: str | None, region: Region) -> float:
        if sku_id is None:
            return 0.0
        return self.available_stock.get((sku_id, region.value), 0.0)

    def is_overstocked(self, sku_id: str | None, region: Region) -> bool:
        return sku_id is not None and (sku_id, region.value) in self.overstocked


def _in_scope(
    products: pd.DataFrame, request: PlanningRequest, sku_ids: Sequence[str] | None
) -> list[str]:
    scope = request.scope
    scoped = {
        str(sku_id)
        for sku_id, category in zip(products["sku_id"], products["category"], strict=True)
        if category in scope.categories and (not scope.sku_ids or sku_id in scope.sku_ids)
    }
    if sku_ids is not None:
        outside = [sku_id for sku_id in sku_ids if sku_id not in scoped]
        if outside:
            raise ValueError(f"not in the planning request's scope: {', '.join(outside)}")
        scoped &= set(sku_ids)
    return sorted(scoped)


def _timings(window: PromoWindow) -> list[tuple[int, int]]:
    """(start week, duration) of every run that starts and ends inside the window."""
    return [
        (start, duration)
        for duration in range(1, MAX_DURATION_WEEKS + 1)
        for start in range(window.start_week, window.end_week - duration + 2)
    ]


def _partners(sku_id: str, relations: RelationLookup, catalogue: _Catalogue) -> list[str]:
    """Detected complements that can partner the SKU in a BUNDLE, highest lift first."""
    return [
        str(partner)
        for partner in relations.complements(sku_id)["sku_id"]
        if partner != sku_id and partner in catalogue.base_price
    ]


def _price_levels(
    mechanisms: list[Mechanism], partners: list[str]
) -> Iterator[tuple[Mechanism, str | None, int]]:
    """Every mechanism, BUNDLE partner and depth, in the order options are listed."""
    for mechanism in mechanisms:
        for partner in partners if mechanism is Mechanism.BUNDLE else [None]:
            for depth in DEPTHS[mechanism]:
                yield mechanism, partner, depth


def _price_reason(
    sku_id: str,
    partner: str | None,
    region: Region,
    mechanism: Mechanism,
    depth: int,
    catalogue: _Catalogue,
    stock: _Stock,
    policy: CompanyPolicy,
) -> PruneReason | None:
    """The first rule the option's prices break, whatever its timing and target."""
    base_price = catalogue.base_price[sku_id]
    try:
        price = effective_unit_price(mechanism, base_price, depth)
    except ValueError:
        return PruneReason.NO_CHARM_PRICE
    if 1 - price / base_price > policy.max_discount_pct / 100 + _EPSILON:
        return PruneReason.MAX_DISCOUNT
    priced = [(sku_id, price)]
    if partner is not None:
        partner_price = effective_unit_price(mechanism, catalogue.base_price[partner], depth)
        priced.append((partner, partner_price))
    for sku, sku_price in priced:
        below = sku_price < catalogue.unit_cost[sku] - _EPSILON
        if below and not stock.is_overstocked(sku, region):
            return PruneReason.BELOW_COST
    return None


def _clearance(
    lines: list[PlanLine],
    table: pd.DataFrame,
    catalogue: _Catalogue,
    stock: _Stock,
    policy: CompanyPolicy,
) -> np.ndarray:
    """Clearance value of each SKU a line sells that is overstocked in its region."""
    value = np.zeros(len(lines))
    sold = (
        ("units", "baseline_units", [line.sku_id for line in lines]),
        ("partner_units", "partner_baseline_units", [line.bundle_partner_sku_id for line in lines]),
    )
    for units, baseline, skus in sold:
        overstocked = np.array(
            [stock.is_overstocked(sku, line.region) for sku, line in zip(skus, lines, strict=True)]
        )
        if not overstocked.any():
            continue
        cost = np.array([catalogue.unit_cost[sku] if sku else 0.0 for sku in skus])
        cleared = clearance_value(
            table[units].to_numpy(dtype=float),
            table[baseline].to_numpy(dtype=float),
            cost,
            policy.write_off_rate,
        )
        value += np.where(overstocked, cleared, 0.0)
    return value


def _counts(pruned: Counter[PruneReason]) -> dict[PruneReason, int]:
    return {reason: pruned[reason] for reason in PruneReason}


def _frozen(
    pruned_by: Mapping[tuple[str, Region, Mechanism], set[PruneReason]],
) -> dict[tuple[str, Region, Mechanism], frozenset[PruneReason]]:
    return {key: frozenset(reasons) for key, reasons in pruned_by.items()}
