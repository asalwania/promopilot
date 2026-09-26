"""The oracle: scores any promo plan by its true expected outcome (ADR 0011).

It evaluates the true demand function from the ground truth (no sampling) over each
plan line's weeks plus the pull-forward window after them, for every SKU in each affected
region, and compares with the no-promotion baseline. Expected units of a promoted SKU are
capped at its pooled available stock (ADR 0004) over the line's weeks, the baseline being
capped the same way; SKUs moved only by cross effects are not capped.

Plan totals come from all of a region's lines together. Per-line figures attribute effects
one line at a time: that line alone against the baseline.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from promopilot.datagen import GeneratedDataset
from promopilot.datagen.truth import MECHANISMS, SEGMENTS, GroundTruth, TrueDemand
from promopilot.domain import CompanyPolicy, PlanLine, PromoPlan, Region, TargetSegment
from promopilot.economics import (
    blended_margin,
    clearance_value,
    discount_funding,
    effective_unit_price,
    fixed_marketing_cost,
    gross_profit,
    incremental_profit,
)

Array = NDArray[np.float64]


@dataclass(frozen=True)
class LineOutcome:
    """True expected outcome of one plan line, attributed as if it ran alone.

    `units`, `baseline_units` and `sell_through` are for the anchor SKU over the line's
    weeks; revenue, gross profit, promo cost and incremental profit include a BUNDLE's
    partner. Incremental profit is net of pull-forward and the fixed marketing cost.
    """

    line: PlanLine
    units: float
    baseline_units: float
    revenue: float
    gross_profit: float
    pull_forward_units: float
    incremental_profit: float
    cannibalisation: float
    halo: float
    promo_cost: float
    clearance_value: float
    sell_through: float | None
    stock_capped: bool


@dataclass(frozen=True)
class PlanOutcome:
    lines: tuple[LineOutcome, ...]
    incremental_profit: float
    """Over every SKU in the affected regions, net of fixed marketing costs."""
    cannibalisation: float
    halo: float
    promo_cost: float
    clearance_value: float
    revenue: float
    gross_profit: float
    blended_margin: float | None
    stock_capped_lines: int

    @property
    def objective(self) -> float:
        """What the planner maximises (ADR 0005): incremental profit plus clearance value."""
        return self.incremental_profit + self.clearance_value


@dataclass(frozen=True)
class _LineFigures:
    revenue: float
    gross_profit: float
    promo_cost: float
    clearance_value: float
    sell_through: float | None


@dataclass(frozen=True)
class _Scenario:
    units: Array  # (weeks, segments, skus), capped
    baseline: Array  # the same, with no promotion, capped over the same line weeks
    prices: Array
    capped: set[int]  # plan-line indices whose SKUs hit the stock cap


class Oracle:
    def __init__(self, truth: GroundTruth, products: pd.DataFrame, inventory: pd.DataFrame) -> None:
        self._truth = truth
        self._demand = TrueDemand(truth)
        self._index = {sku_id: i for i, sku_id in enumerate(self._demand.sku_ids)}
        by_sku = products.set_index("sku_id").loc[self._demand.sku_ids]
        self._costs: Array = by_sku["unit_cost"].to_numpy(dtype=float)
        self._region_of = {store.store_id: store.region for store in truth.stores}
        self._inventory = inventory

    @classmethod
    def from_dataset(cls, dataset: GeneratedDataset) -> "Oracle":
        return cls(dataset.ground_truth, dataset.products, dataset.inventory)

    def evaluate(self, plan: PromoPlan, as_of_week: int, policy: CompanyPolicy) -> PlanOutcome:
        for line in plan.lines:
            if line.start_week < as_of_week:
                raise ValueError(
                    f"{line.sku_id} in {line.region} starts in week {line.start_week}, "
                    f"before the as-of week {as_of_week}"
                )
            if line.start_week + line.duration_weeks > self._truth.total_weeks:
                raise ValueError(f"{line.sku_id} in {line.region} runs past the generated timeline")
        available, overstocked = self._stock(as_of_week, policy) if plan.lines else ({}, set())

        outcomes: dict[int, LineOutcome] = {}
        totals = dict.fromkeys(
            ["incremental", "cannibalisation", "halo", "promo_cost", "clearance"], 0.0
        )
        revenues: list[float] = []
        profits: list[float] = []
        capped_lines = 0
        for region in dict.fromkeys(line.region for line in plan.lines):
            numbered = [(i, line) for i, line in enumerate(plan.lines) if line.region is region]
            lines = [line for _, line in numbered]
            start = min(line.start_week for line in lines)
            end = max(line.start_week + line.duration_weeks for line in lines)
            weeks = slice(
                start, min(end + self._truth.pull_forward_window_weeks, self._truth.total_weeks)
            )
            baseline = self._expected(region, weeks, [])

            joint = self._scenario(region, weeks, lines, baseline, available)
            occupied = {self._index[sku] for line in lines for sku in line.skus}
            cannibalisation, halo = self._cross_effects(joint, occupied)
            totals["cannibalisation"] += cannibalisation
            totals["halo"] += halo
            totals["incremental"] += float(
                (
                    self._gross_profit(joint.units, joint.prices)
                    - self._gross_profit(joint.baseline, None)
                ).sum()
            ) - sum(
                fixed_marketing_cost(line.mechanism, line.duration_weeks, policy) for line in lines
            )
            capped_lines += len(joint.capped)
            for n, line in enumerate(lines):
                figures = self._line_figures(
                    line, joint, weeks.start, available, overstocked, policy
                )
                totals["promo_cost"] += figures.promo_cost
                totals["clearance"] += figures.clearance_value
                revenues.append(figures.revenue)
                profits.append(figures.gross_profit)

                alone = self._scenario(region, weeks, [line], baseline, available)
                own = {self._index[sku] for sku in line.skus}
                line_cannibalisation, line_halo = self._cross_effects(alone, own)
                figures = self._line_figures(
                    line, alone, weeks.start, available, overstocked, policy
                )
                anchor = self._index[line.sku_id]
                line_weeks = slice(
                    line.start_week - weeks.start,
                    line.start_week - weeks.start + line.duration_weeks,
                )
                after = slice(line_weeks.stop, None)
                own_list = sorted(own)
                outcomes[numbered[n][0]] = LineOutcome(
                    line=line,
                    units=float(alone.units[line_weeks, :, anchor].sum()),
                    baseline_units=float(alone.baseline[line_weeks, :, anchor].sum()),
                    revenue=figures.revenue,
                    gross_profit=figures.gross_profit,
                    pull_forward_units=float(
                        (alone.baseline[after, :, anchor] - alone.units[after, :, anchor]).sum()
                    ),
                    incremental_profit=float(
                        incremental_profit(
                            float(self._gross_profit(alone.units, alone.prices)[own_list].sum()),
                            float(self._gross_profit(alone.baseline, None)[own_list].sum()),
                            fixed_marketing_cost(line.mechanism, line.duration_weeks, policy),
                        )
                    ),
                    cannibalisation=line_cannibalisation,
                    halo=line_halo,
                    promo_cost=figures.promo_cost,
                    clearance_value=figures.clearance_value,
                    sell_through=figures.sell_through,
                    stock_capped=bool(alone.capped),
                )

        return PlanOutcome(
            lines=tuple(outcomes[i] for i in range(len(plan.lines))),
            incremental_profit=totals["incremental"],
            cannibalisation=totals["cannibalisation"],
            halo=totals["halo"],
            promo_cost=totals["promo_cost"],
            clearance_value=totals["clearance"],
            revenue=sum(revenues),
            gross_profit=sum(profits),
            blended_margin=blended_margin(revenues, profits),
            stock_capped_lines=capped_lines,
        )

    def _stock(
        self, as_of_week: int, policy: CompanyPolicy
    ) -> tuple[dict[tuple[Region, int], float], set[tuple[Region, int]]]:
        """Pooled available stock and overstock status per region and SKU at the as-of week."""
        snapshot = self._inventory[self._inventory["snapshot_week"] == as_of_week - 1]
        if snapshot.empty:
            raise LookupError(f"no inventory snapshot for the end of week {as_of_week - 1}")
        rows = snapshot.assign(
            region=snapshot["store_id"].map(self._region_of),
            free=snapshot["on_hand"] - snapshot["safety_stock"],
            daily_demand=np.where(
                snapshot["days_of_cover"] > 0, snapshot["on_hand"] / snapshot["days_of_cover"], 0.0
            ),
        )
        pooled = rows.groupby(["region", "sku_id"])[["free", "on_hand", "daily_demand"]].sum()
        available: dict[tuple[Region, int], float] = {}
        overstocked: set[tuple[Region, int]] = set()
        threshold_days = policy.overstock_threshold_weeks * 7
        for region, sku_id, free, on_hand, demand in pooled.reset_index().itertuples(
            index=False, name=None
        ):
            key = (Region(region), self._index[sku_id])
            available[key] = max(float(free), 0.0)
            days_of_cover = on_hand / demand if demand > 0 else (np.inf if on_hand > 0 else 0.0)
            if days_of_cover > threshold_days:
                overstocked.add(key)
        return available, overstocked

    def _prices(self, weeks: slice, lines: list[PlanLine]) -> tuple[Array, NDArray[np.int_]]:
        length = weeks.stop - weeks.start
        prices = np.tile(self._demand.reference_prices, (length, len(SEGMENTS), 1))
        mechanisms = np.full(prices.shape, -1)
        for line in lines:
            span = slice(
                line.start_week - weeks.start, line.start_week - weeks.start + line.duration_weeks
            )
            for g in self._segments(line.target_segment):
                for sku in line.skus:
                    i = self._index[sku]
                    prices[span, g, i] = effective_unit_price(
                        line.mechanism, float(self._demand.reference_prices[i]), line.depth_pct
                    )
                mechanisms[span, g, self._index[line.sku_id]] = MECHANISMS.index(line.mechanism)
        return prices, mechanisms

    def _expected(self, region: Region, weeks: slice, lines: list[PlanLine]) -> Array:
        prices, mechanisms = self._prices(weeks, lines)
        units = self._demand.expected_units(region, weeks.start, prices, mechanisms)
        return np.asarray(units.sum(axis=0))  # pool the region's stores: (W, G, N)

    def _scenario(
        self,
        region: Region,
        weeks: slice,
        lines: list[PlanLine],
        baseline: Array,
        available: dict[tuple[Region, int], float],
    ) -> _Scenario:
        units = self._expected(region, weeks, lines)
        capped_baseline = baseline.copy()
        capped: set[int] = set()
        for n, line in enumerate(lines):
            span = slice(
                line.start_week - weeks.start, line.start_week - weeks.start + line.duration_weeks
            )
            for sku in line.skus:
                i = self._index[sku]
                stock = available.get((region, i), 0.0)
                for array in (units, capped_baseline):
                    total = array[span, :, i].sum()
                    if total > stock:
                        array[span, :, i] *= stock / total
                        if array is units:
                            capped.add(n)
        prices, _ = self._prices(weeks, lines)
        return _Scenario(units=units, baseline=capped_baseline, prices=prices, capped=capped)

    def _gross_profit(self, units: Array, prices: Array | None) -> Array:
        """Gross profit per SKU over the scenario weeks; None means reference prices."""
        price = self._demand.reference_prices if prices is None else prices
        return np.asarray(gross_profit(units, price, self._costs).sum(axis=(0, 1)))

    def _cross_effects(self, scenario: _Scenario, own: set[int]) -> tuple[float, float]:
        delta = self._gross_profit(scenario.units, scenario.prices) - self._gross_profit(
            scenario.baseline, None
        )
        others = np.array([i not in own for i in range(len(delta))])
        return float(-delta[others & (delta < 0)].sum()), float(delta[others & (delta > 0)].sum())

    def _line_figures(
        self,
        line: PlanLine,
        scenario: _Scenario,
        first_week: int,
        available: dict[tuple[Region, int], float],
        overstocked: set[tuple[Region, int]],
        policy: CompanyPolicy,
    ) -> _LineFigures:
        span = slice(
            line.start_week - first_week, line.start_week - first_week + line.duration_weeks
        )
        revenue = profit = funding = clearance = 0.0
        for sku in line.skus:
            i = self._index[sku]
            units = scenario.units[span, :, i]
            prices = scenario.prices[span, :, i]
            reference = float(self._demand.reference_prices[i])
            revenue += float((units * prices).sum())
            profit += float(gross_profit(units, prices, float(self._costs[i])).sum())
            by_segment = {segment: float(units[:, g].sum()) for g, segment in enumerate(SEGMENTS)}
            effective = effective_unit_price(line.mechanism, reference, line.depth_pct)
            funding += discount_funding(reference, effective, by_segment, line.target_segment)
            if (line.region, i) in overstocked:
                clearance += clearance_value(
                    float(units.sum()),
                    float(scenario.baseline[span, :, i].sum()),
                    float(self._costs[i]),
                    policy.write_off_rate,
                )
        anchor = self._index[line.sku_id]
        stock = available.get((line.region, anchor), 0.0)
        sold = float(scenario.units[span, :, anchor].sum())
        return _LineFigures(
            revenue=revenue,
            gross_profit=profit,
            promo_cost=funding + fixed_marketing_cost(line.mechanism, line.duration_weeks, policy),
            clearance_value=clearance,
            sell_through=sold / stock if stock > 0 else None,
        )

    @staticmethod
    def _segments(target: TargetSegment) -> list[int]:
        if target is TargetSegment.ALL_CUSTOMERS:
            return list(range(len(SEGMENTS)))
        return [[g.value for g in SEGMENTS].index(target.value)]
