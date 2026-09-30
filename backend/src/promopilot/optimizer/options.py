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

A SKU the brief names for clearance is overstocked in every region of the scope (ADR 0014),
and its options, as anchor or BUNDLE partner, carry their uplift over the promo window, which
the optimiser's clearance targets read (ADR 0040). A KVI a competitor undercuts gets a
price-match option: PCT_OFF at the smallest whole-percent depth that reaches the
competitor's price, when that depth is not already on the grid (ADR 0031, ADR 0040).
"""

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from promopilot.competitors import CompetitorGaps
from promopilot.domain import (
    P90_Z,
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
from promopilot.guardrails import SkuFacts, SubstituteFacts
from promopilot.models.demand import OPTION_COLUMNS, Prediction, PredictionContext
from promopilot.models.relations import (
    LineForecast,
    RelationLookup,
    line_effect_totals,
    pairwise_cannibalisations,
)

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
    competitor_gaps: CompetitorGaps | None = None
    """The latest competitor gaps (ADR 0031): undercut KVIs get price-match options, and the
    optimiser checks the KVI price tolerance against them."""


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
    "window_uplift",
    "partner_window_uplift",
]
"""`PromoOptions.table`: the demand model's OPTION_COLUMNS, then P90 units against stock
(the partner's are 0 without a BUNDLE), the line's cannibalisation, halo and clearance value,
and value = incremental_profit - cannibalised_profit + halo_profit + clearance_value, what
the option is worth if it runs alone. Money in rupees (ADR 0015).

window_uplift and partner_window_uplift are the change in the anchor's and the partner's
expected units over the promo window: promo-week units less baseline, net of the pull-forward
dip that falls inside the window. They are computed only for a SKU with a clearance target,
and are 0 otherwise (ADR 0040)."""


@dataclass(frozen=True)
class ClearanceBaseline:
    """What a SKU with a clearance target sells over the promo window with no promotion, and
    the stock it is measured against, in one region (ADR 0040)."""

    sku_id: str
    region: Region
    available_stock: float
    """Pooled available stock at the as-of week (ADR 0004): positive."""
    baseline_units: float
    """Expected units over the promo window with no promotion."""


@dataclass(frozen=True)
class PriceMatch:
    """The price-match level of a KVI a competitor undercuts in a region (ADR 0040)."""

    sku_id: str
    region: Region
    depth_pct: int
    """The smallest whole-percent PCT_OFF depth at or below the competitor's price."""
    competitor_price: float


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
    clearance: tuple[ClearanceBaseline, ...] = ()
    """One per clearance target and region of the scope with available stock."""
    price_matches: tuple[PriceMatch, ...] = ()
    """The price-match level of each undercut KVI in scope, enumerated as PCT_OFF."""
    _tally: "_Tally | None" = field(default=None, repr=False, compare=False)
    """What was enumerated and pruned per anchor SKU, region, mechanism and target segment,
    so a narrower set can be read off this one (`generate_options` with `unnarrowed`, ADR
    0077); None for a set built by hand."""


_Key = tuple[str, Region, Mechanism, TargetSegment]


@dataclass(frozen=True)
class _Tally:
    """Options enumerated, and pruned per reason, per anchor SKU, region, mechanism and target
    segment: the counts of generation, at the grain every narrowing keeps or drops whole."""

    enumerated: Mapping[_Key, int]
    pruned: Mapping[_Key, Mapping[PruneReason, int]]


class FittedOptionFacts:
    """What the optimiser reads beyond the options' own numbers (`OptionFacts`, ADR 0036),
    from the context the options were generated in: each SKU's category, prices and
    overstock flag, and the pairwise cannibalisation of option pairs on the same models.

    Each option pair is priced once: a later call for the same pair of line objects, such as
    the Critic's loop-back solving a narrower set read off the first (ADR 0077), gets the
    term already priced."""

    def __init__(self, context: OptionContext) -> None:
        self._context = context
        self._priced = _PricedPairs()
        self._catalogue = _Catalogue.of(context.products)
        self._stock = _Stock.of(context.stock)
        products = context.products
        self._categories = dict(
            zip(products["sku_id"].astype(str), products["category"].astype(str), strict=True)
        )
        gaps = context.competitor_gaps.gaps if context.competitor_gaps is not None else ()
        self._gaps = {(gap.region, gap.sku_id): gap for gap in gaps}

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        gap = self._gaps.get((region, sku_id))
        return SkuFacts(
            category=self._categories[sku_id],
            base_price=self._catalogue.base_price[sku_id],
            unit_cost=self._catalogue.unit_cost[sku_id],
            overstocked=self._stock.is_overstocked(sku_id, region),
            is_kvi=gap is not None and gap.is_kvi,
            competitor_price=None if gap is None else gap.competitor_price,
        )

    @property
    def context(self) -> OptionContext:
        """The context the facts, and the options they were built with, come from."""
        return self._context

    def pairwise_cannibalisation(self, pairs: Sequence[tuple[PlanLine, PlanLine]]) -> np.ndarray:
        context = self._context

        def price(missing: Sequence[tuple[PlanLine, PlanLine]]) -> np.ndarray:
            return pairwise_cannibalisations(
                missing,
                context.relations,
                context.demand_model,
                context.products,
                PredictionContext(
                    policy=context.policy, competitor_prices=context.competitor_prices
                ),
            )

        return self._priced.terms(pairs, price)

    def substitutes(self, sku_ids: Sequence[str]) -> list[SubstituteFacts]:
        """The relations model's detected substitute pairs among these SKUs, each once and
        sorted, with its estimated θ (ADR 0075). The model has one θ per pair; a lookup with
        a θ per direction gives the larger, as the eval does (ADR 0065)."""
        wanted = set(sku_ids)
        found: dict[tuple[str, str], float] = {}
        for sku_id in sorted(wanted):
            partners = self._context.relations.substitutes(sku_id)
            for partner, theta in zip(partners["sku_id"], partners["theta"], strict=True):
                partner = str(partner)
                if partner in wanted and partner != sku_id and np.isfinite(theta):
                    key = (min(sku_id, partner), max(sku_id, partner))
                    found[key] = max(found.get(key, -np.inf), float(theta))
        return [
            SubstituteFacts(sku_id=a, other_sku_id=b, theta=theta)
            for (a, b), theta in sorted(found.items())
        ]


class _PricedPairs:
    """Pairwise terms already priced, per ordered pair of line objects. Lines are told apart
    by identity, as `pairwise_cannibalisations` tells them, and each is kept so its id stays
    its own. The pairs are kept as sorted codes with their terms: a few hundred thousand on
    the demo brief (ADR 0077)."""

    def __init__(self) -> None:
        self._index: dict[int, int] = {}
        self._lines: list[PlanLine] = []
        self._codes = np.zeros(0, dtype=np.int64)
        self._terms = np.zeros(0)

    def terms(
        self,
        pairs: Sequence[tuple[PlanLine, PlanLine]],
        price: Callable[[Sequence[tuple[PlanLine, PlanLine]]], np.ndarray],
    ) -> np.ndarray:
        """Each pair's term, in order, pricing only the pairs never priced before."""
        codes = np.fromiter(
            ((self._number(a) << 32) | self._number(b) for a, b in pairs),
            dtype=np.int64,
            count=len(pairs),
        )
        at = np.searchsorted(self._codes, codes)
        found = at < len(self._codes)
        found[found] = self._codes[at[found]] == codes[found]
        result = np.zeros(len(pairs))
        result[found] = self._terms[at[found]]
        missing = np.flatnonzero(~found)
        if missing.size:
            priced = np.asarray(price([pairs[k] for k in missing.tolist()]), dtype=float)
            result[missing] = priced
            new, first = np.unique(codes[missing], return_index=True)
            codes_all = np.concatenate([self._codes, new])
            order = np.argsort(codes_all, kind="stable")
            self._codes = codes_all[order]
            self._terms = np.concatenate([self._terms, priced[first]])[order]
        return result

    def _number(self, line: PlanLine) -> int:
        number = self._index.get(id(line))
        if number is None:
            number = self._index[id(line)] = len(self._lines)
            self._lines.append(line)
        return number


def generate_options(
    request: PlanningRequest,
    context: OptionContext,
    *,
    mechanisms: Sequence[Mechanism] | None = None,
    target_segments: Sequence[TargetSegment] | None = None,
    sku_ids: Sequence[str] | None = None,
    exclude_sku_ids: Sequence[str] | None = None,
    unnarrowed: PromoOptions | None = None,
) -> PromoOptions:
    """The promo options for the planning request's scope and promo window.

    `mechanisms`, `target_segments` and `sku_ids` narrow the enumeration further, and
    `exclude_sku_ids` leaves SKUs out (ADR 0059). A ValueError for: a SKU outside the request's
    scope, a SKU both kept and left out, leaving out every SKU or a clearance target of the
    brief, and an option the demand model cannot predict.

    `unnarrowed` is the set generated for the same request in the same context with no
    narrowing. The narrowed set is then read off it, its rows and its counts, instead of
    being enumerated and predicted again: the Critic's loop-back leaves a SKU out of the set
    the planner generated first (ADR 0077). Every option is predicted on its own, so the rows
    are the ones a narrowed generation predicts.
    """
    catalogue = _Catalogue.of(context.products)
    cleared = _clearance_skus(context.products, request)
    stock = _Stock.of(context.stock).with_overstocked(cleared, request.scope.regions)
    timings = _timings(request.promo_window)
    targets = [
        target for target in TargetSegment if target_segments is None or target in target_segments
    ]
    chosen = [mechanism for mechanism in Mechanism if mechanisms is None or mechanism in mechanisms]
    per_price = len(timings) * len(targets)
    scoped = _in_scope(context.products, request, sku_ids)
    if exclude_sku_ids:
        scoped = _left_out(scoped, context.products, request, sku_ids, exclude_sku_ids, cleared)
    matches = _price_matches(context.competitor_gaps, request, set(scoped), catalogue)
    if unnarrowed is not None and unnarrowed._tally is not None and chosen and targets:
        return _narrowed(unnarrowed, unnarrowed._tally, set(scoped), chosen, targets, matches)

    pruned: Counter[PruneReason] = Counter()
    enumerated_by: Counter[_Key] = Counter()
    pruned_by_key: defaultdict[_Key, Counter[PruneReason]] = defaultdict(Counter)
    pruned_by: defaultdict[tuple[str, Region, Mechanism], set[PruneReason]] = defaultdict(set)
    enumerated = 0
    lines: list[PlanLine] = []
    for sku_id in scoped:
        partners = _partners(sku_id, context.relations, catalogue)
        for region in request.scope.regions:
            charm_prices: set[float] = set()
            levels = list(_price_levels(chosen, partners))
            match = next((m for m in matches if (m.sku_id, m.region) == (sku_id, region)), None)
            if (
                match is not None
                and Mechanism.PCT_OFF in chosen
                and match.depth_pct not in DEPTHS[Mechanism.PCT_OFF]
            ):
                levels.append((Mechanism.PCT_OFF, None, match.depth_pct))
            for mechanism, partner, depth in levels:
                enumerated += per_price
                reason = _price_reason(
                    sku_id, partner, region, mechanism, depth, catalogue, stock, context.policy
                )
                if reason is None and mechanism is Mechanism.FIXED_PRICE:
                    price = effective_unit_price(mechanism, catalogue.base_price[sku_id], depth)
                    if price in charm_prices:
                        reason = PruneReason.DUPLICATE_PRICE
                    charm_prices.add(price)
                for target in targets:
                    enumerated_by[sku_id, region, mechanism, target] += len(timings)
                    if reason is not None:
                        pruned_by_key[sku_id, region, mechanism, target][reason] += len(timings)
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

    prediction_context = PredictionContext(
        policy=context.policy, competitor_prices=context.competitor_prices
    )
    clearance = _clearance_baselines(
        cleared, request, context.demand_model, stock, prediction_context
    )
    if not lines:
        return PromoOptions(
            (),
            pd.DataFrame(columns=TABLE_COLUMNS),
            enumerated,
            _counts(pruned),
            pruned_by_mechanism=_frozen(pruned_by),
            clearance=clearance,
            price_matches=tuple(matches),
            _tally=_tally(enumerated_by, pruned_by_key),
        )
    prediction = context.demand_model.predict(lines, prediction_context)
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
        pruned_by_key[line.sku_id, line.region, line.mechanism, line.target_segment][reason] += 1
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
    anchor_uplift, partner_uplift = _window_uplifts(
        kept, cleared, request.promo_window, context.demand_model, prediction_context
    )
    table["window_uplift"] = anchor_uplift
    table["partner_window_uplift"] = partner_uplift
    return PromoOptions(
        tuple(kept),
        table[TABLE_COLUMNS],
        enumerated,
        _counts(pruned),
        pruned_by_mechanism=_frozen(pruned_by),
        clearance=clearance,
        price_matches=tuple(matches),
        _tally=_tally(enumerated_by, pruned_by_key),
    )


_PREDICTED_REASONS = (PruneReason.STOCK, PruneReason.PARTNER_STOCK)
"""The reasons an option is pruned for after it is predicted."""


def _tally(enumerated: Mapping[_Key, int], pruned: Mapping[_Key, Counter[PruneReason]]) -> _Tally:
    return _Tally(dict(enumerated), {key: dict(reasons) for key, reasons in pruned.items()})


def _narrowed(
    unnarrowed: PromoOptions,
    tally: _Tally,
    skus: set[str],
    mechanisms: list[Mechanism],
    targets: list[TargetSegment],
    matches: list[PriceMatch],
) -> PromoOptions:
    """The options of `unnarrowed` whose anchor SKU, mechanism and target segment the
    narrowing keeps, with the counts of generation for those alone (ADR 0077)."""

    def kept(key: _Key) -> bool:
        sku_id, _, mechanism, target = key
        return sku_id in skus and mechanism in mechanisms and target in targets

    pruned: Counter[PruneReason] = Counter()
    pruned_by: defaultdict[tuple[str, Region, Mechanism], set[PruneReason]] = defaultdict(set)
    for key, reasons in tally.pruned.items():
        if kept(key):
            for reason, count in reasons.items():
                pruned[reason] += count
                pruned_by[key[:3]].add(reason)
    rows = [
        n
        for n, line in enumerate(unnarrowed.lines)
        if kept((line.sku_id, line.region, line.mechanism, line.target_segment))
    ]
    enumerated = sum(count for key, count in tally.enumerated.items() if kept(key))
    predicted = enumerated - sum(
        count for reason, count in pruned.items() if reason not in _PREDICTED_REASONS
    )
    # With nothing to predict, generation returns an untyped empty table.
    table = (
        unnarrowed.table.iloc[rows].reset_index(drop=True)
        if predicted
        else pd.DataFrame(columns=TABLE_COLUMNS)
    )
    return PromoOptions(
        tuple(unnarrowed.lines[n] for n in rows),
        table,
        enumerated,
        _counts(pruned),
        pruned_by_mechanism=_frozen(pruned_by),
        clearance=unnarrowed.clearance,
        price_matches=tuple(matches),
        _tally=_Tally(
            {key: count for key, count in tally.enumerated.items() if kept(key)},
            {key: reasons for key, reasons in tally.pruned.items() if kept(key)},
        ),
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

    def with_overstocked(self, sku_ids: Sequence[str], regions: Sequence[Region]) -> "_Stock":
        """The same stock, with these SKUs overstocked in these regions too."""
        extra = {(sku_id, region.value) for sku_id in sku_ids for region in regions}
        return _Stock(self.available_stock, self.overstocked | extra)


def _clearance_skus(products: pd.DataFrame, request: PlanningRequest) -> list[str]:
    """The SKUs the brief names for clearance, all in the request's scope."""
    scoped = set(_in_scope(products, request, None))
    named = [target.sku_id for target in request.clearance_targets]
    outside = [sku_id for sku_id in named if sku_id not in scoped]
    if outside:
        raise ValueError(
            f"a clearance target names SKUs outside the planning request's scope: "
            f"{', '.join(outside)}"
        )
    return named


def _price_matches(
    gaps: CompetitorGaps | None,
    request: PlanningRequest,
    scoped: set[str],
    catalogue: _Catalogue,
) -> list[PriceMatch]:
    """The price-match level of each KVI undercut in a region of the scope (ADR 0040)."""
    if gaps is None:
        return []
    matches = []
    for gap in sorted(gaps.gaps, key=lambda gap: (gap.sku_id, list(Region).index(gap.region))):
        if not gap.undercut or gap.sku_id not in scoped or gap.region not in request.scope.regions:
            continue
        base_price = catalogue.base_price[gap.sku_id]
        depth = max(1, math.floor((1 - gap.competitor_price / base_price) * 100))
        while (
            depth < 100
            and effective_unit_price(Mechanism.PCT_OFF, base_price, depth)
            > gap.competitor_price + _EPSILON
        ):
            depth += 1
        matches.append(PriceMatch(gap.sku_id, gap.region, depth, gap.competitor_price))
    return matches


def _clearance_baselines(
    cleared: Sequence[str],
    request: PlanningRequest,
    demand: OptionForecast,
    stock: _Stock,
    context: PredictionContext,
) -> tuple[ClearanceBaseline, ...]:
    """Each clearance SKU's window baseline and available stock, per region with stock.

    The baseline is the demand model's own no-promotion units (`baseline_units`) of lines
    that cover the window, so it is on the same footing as each option's uplift.
    """
    window = request.promo_window
    chunks = [
        (start, min(MAX_DURATION_WEEKS, window.end_week - start + 1))
        for start in range(window.start_week, window.end_week + 1, MAX_DURATION_WEEKS)
    ]
    keys = [
        (sku_id, region)
        for sku_id in sorted(cleared)
        for region in request.scope.regions
        if stock.available(sku_id, region) > 0
    ]
    if not keys:
        return ()
    covering = [
        PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=DEPTHS[Mechanism.PCT_OFF][0],
            duration_weeks=duration,
            start_week=start,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        )
        for sku_id, region in keys
        for start, duration in chunks
    ]
    baseline = demand.predict(covering, context).options["baseline_units"].to_numpy(float)
    per_key = baseline.reshape(len(keys), len(chunks)).sum(axis=1)
    return tuple(
        ClearanceBaseline(
            sku_id=sku_id,
            region=region,
            available_stock=stock.available(sku_id, region),
            baseline_units=float(units),
        )
        for (sku_id, region), units in zip(keys, per_key, strict=True)
    )


def _window_uplifts(
    lines: Sequence[PlanLine],
    cleared: Sequence[str],
    window: PromoWindow,
    demand: OptionForecast,
    context: PredictionContext,
) -> tuple[np.ndarray, np.ndarray]:
    """Each line's change in its anchor's and its partner's units over the promo window,
    net of the pull-forward dip inside it; computed only for SKUs with a clearance target."""
    anchor, partner = np.zeros(len(lines)), np.zeros(len(lines))
    names = set(cleared)
    rows = [n for n, line in enumerate(lines) if names & set(line.skus)]
    if not rows:
        return anchor, partner
    paths = demand.line_paths([lines[n] for n in rows], context)
    inside = paths[(paths["week_id"] >= window.start_week) & (paths["week_id"] <= window.end_week)]
    change = (
        (inside["units"] - inside["baseline_units"])
        .groupby([inside["option"], inside["sku_id"]])
        .sum()
    )
    for k, n in enumerate(rows):
        line = lines[n]
        if line.sku_id in names:
            anchor[n] = float(change.get((k, line.sku_id), 0.0))
        if line.bundle_partner_sku_id in names:
            partner[n] = float(change.get((k, line.bundle_partner_sku_id), 0.0))
    return anchor, partner


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


def _left_out(
    scoped: list[str],
    products: pd.DataFrame,
    request: PlanningRequest,
    sku_ids: Sequence[str] | None,
    exclude_sku_ids: Sequence[str],
    cleared: Sequence[str],
) -> list[str]:
    """The scoped SKUs without those left out."""
    in_scope = set(_in_scope(products, request, None))
    outside = [sku_id for sku_id in exclude_sku_ids if sku_id not in in_scope]
    if outside:
        raise ValueError(f"not in the planning request's scope: {', '.join(outside)}")
    both = [sku_id for sku_id in exclude_sku_ids if sku_ids is not None and sku_id in sku_ids]
    if both:
        raise ValueError(f"both kept and left out: {', '.join(both)}")
    targets = [sku_id for sku_id in exclude_sku_ids if sku_id in cleared]
    if targets:
        raise ValueError(f"may not leave out a clearance target of the brief: {', '.join(targets)}")
    kept = [sku_id for sku_id in scoped if sku_id not in set(exclude_sku_ids)]
    if not kept:
        raise ValueError("leaving these SKUs out leaves no SKU to promote")
    return kept


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
