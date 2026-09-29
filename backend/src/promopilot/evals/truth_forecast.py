"""The demand and relations models' interfaces, answered from the ground truth (ADR 0063).

The best plan regret is measured against is our own optimiser run on true parameters: option
generation and CP-SAT exactly as a session runs them, with these two in place of the fitted
models. `TrueForecast` predicts each promo option with the oracle's true demand function
(`TrueDemand`), one line alone as the oracle attributes a line: expected units over the
promo weeks and the pull-forward weeks after them, the true competitor prices included. The
spread behind P90 is the true negative-binomial noise of store-level sales, with no parameter
uncertainty. `TrueRelations` lists the true substitute and complement pairs with the true
cross effect of a SKU's price on its partner.

Only promopilot.evals may use these: they read the ground truth (ADR 0003).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from promopilot.datagen.truth import MECHANISMS, SEGMENTS, GroundTruth, TrueDemand
from promopilot.domain import PlanLine, Region, TargetSegment
from promopilot.economics import effective_unit_price, fixed_marketing_cost
from promopilot.models.demand import OPTION_COLUMNS, Prediction, PredictionContext

Array = NDArray[np.float64]
SEGMENT_NAMES = [segment.value for segment in SEGMENTS]
PATH_COLUMNS = ["option", "week_id", "sku_id", "segment", "units", "baseline_units", "price"]
BASELINE_COLUMNS = ["week_id", "store_id", "sku_id", "segment", "units"]


@dataclass(frozen=True)
class _Path:
    """One line alone over its promo weeks and the pull-forward weeks after them, summed over
    the region's stores: arrays of shape (weeks, segments, the line's SKUs)."""

    line: PlanLine
    units: Array
    variance: Array
    baseline: Array
    prices: Array
    reference: Array
    costs: Array

    @property
    def weeks(self) -> range:
        return range(self.line.start_week, self.line.start_week + self.units.shape[0])


class TrueForecast:
    """`promopilot.models.demand.DemandModel`'s `predict`, `line_paths` and `baseline`, on the
    true demand function. `PredictionContext.competitor_prices` is ignored: the true
    competitor prices apply, as the oracle scores them."""

    def __init__(self, truth: GroundTruth, products: pd.DataFrame, as_of_week: int) -> None:
        self._demand = TrueDemand(truth)
        sku_ids = self._demand.sku_ids
        costs = products.set_index("sku_id")["unit_cost"].astype(float)
        self._reference = dict(zip(sku_ids, map(float, self._demand.reference_prices), strict=True))
        self._cost = {sku_id: float(costs[sku_id]) for sku_id in sku_ids}
        self._size = dict(zip(sku_ids, map(float, self._demand.dispersion), strict=True))
        self._after = truth.pull_forward_window_weeks
        self._total_weeks = truth.total_weeks
        self._regions = {store.region for store in truth.stores}
        self.as_of_week = as_of_week
        self._baselines: dict[tuple[Region, int, int, tuple[str, ...]], Array] = {}

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        """Each option's true expected outcome as if it ran alone: OPTION_COLUMNS, meaning
        what `DemandModel.predict`'s mean. Raises ValueError for an option it cannot predict."""
        rows = []
        segments = []
        for n, path in enumerate(self._paths(options)):
            line = path.line
            promo = slice(0, line.duration_weeks)
            after = slice(line.duration_weeks, None)
            units, baseline, prices = path.units, path.baseline, path.prices
            discount = (path.reference - prices) * units
            fixed = fixed_marketing_cost(line.mechanism, line.duration_weeks, context.policy)
            revenue = float((units[promo] * prices[promo]).sum())
            profit = float((units[promo] * (prices[promo] - path.costs)).sum())
            partner = units.shape[2] > 1
            rows.append(
                {
                    "units": float(units[promo, :, 0].sum()),
                    "units_std": float(np.sqrt(path.variance[promo, :, 0].sum())),
                    "baseline_units": float(baseline[promo, :, 0].sum()),
                    "pull_forward_units": float((baseline[after, :, 0] - units[after, :, 0]).sum()),
                    "incremental_units": float((units[:, :, 0] - baseline[:, :, 0]).sum()),
                    "revenue": revenue,
                    "gross_profit": profit,
                    "margin": profit / revenue if revenue > 0 else 0.0,
                    "promo_cost": float(discount[promo].sum()) + fixed,
                    "incremental_profit": float(
                        (units * (prices - path.costs)).sum()
                        - (baseline * (path.reference - path.costs)).sum()
                    )
                    - fixed,
                    "anchor_discount_funding": float(discount[promo, :, 0].sum()),
                    "partner_units": float(units[promo, :, 1].sum()) if partner else 0.0,
                    "partner_units_std": float(np.sqrt(path.variance[promo, :, 1].sum()))
                    if partner
                    else 0.0,
                    "partner_baseline_units": float(baseline[promo, :, 1].sum())
                    if partner
                    else 0.0,
                    "partner_discount_funding": float(discount[promo, :, 1].sum())
                    if partner
                    else 0.0,
                }
            )
            segments += [
                {
                    "option": n,
                    "segment": name,
                    "units": float(units[promo, g, 0].sum()),
                    "units_std": float(np.sqrt(path.variance[promo, g, 0].sum())),
                    "baseline_units": float(baseline[promo, g, 0].sum()),
                }
                for g, name in enumerate(SEGMENT_NAMES)
            ]
        return Prediction(
            options=pd.DataFrame(rows, columns=OPTION_COLUMNS),
            segments=pd.DataFrame(
                segments, columns=["option", "segment", "units", "units_std", "baseline_units"]
            ),
        )

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        """PATH_COLUMNS: each option's SKUs per week and segment, over its region."""
        frames: dict[str, list[NDArray[np.generic]]] = {column: [] for column in PATH_COLUMNS}
        for n, path in enumerate(self._paths(options)):
            weeks, segments, skus = path.units.shape
            size = weeks * segments * skus
            # (weeks, SKUs, segments) order, as `DemandModel.line_paths` sorts its rows.
            frames["option"].append(np.full(size, n))
            frames["week_id"].append(np.repeat(np.array(path.weeks), skus * segments))
            frames["sku_id"].append(np.tile(np.repeat(path.line.skus, segments), weeks))
            frames["segment"].append(np.tile(SEGMENT_NAMES, weeks * skus))
            for column, values in (
                ("units", path.units),
                ("baseline_units", path.baseline),
                ("price", path.prices),
            ):
                frames[column].append(values.transpose(0, 2, 1).ravel())
        if not frames["option"]:
            return pd.DataFrame(columns=PATH_COLUMNS)
        return pd.DataFrame({column: np.concatenate(parts) for column, parts in frames.items()})

    def baseline(
        self,
        weeks: Iterable[int],
        *,
        regions: Sequence[str] | None = None,
        store_ids: Sequence[str] | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """BASELINE_COLUMNS: no-promotion units for every store x SKU x segment in the weeks."""
        weeks = sorted(set(weeks))
        skus = list(self._demand.sku_ids if sku_ids is None else sku_ids)
        chosen = [Region(r) for r in regions] if regions is not None else sorted(self._regions)
        frames = []
        if weeks and skus:
            if weeks[0] < 0 or weeks[-1] >= self._total_weeks:
                raise ValueError(f"weeks outside the calendar: {weeks}")
            first, length = weeks[0], weeks[-1] - weeks[0] + 1
            at = [week - first for week in weeks]
            for region in chosen:
                if region not in self._regions:
                    continue
                stores = self._demand.store_ids(region)
                units = self._unpromoted(region, first, length, skus)[:, at]  # (S, W, G, k)
                keep = [s for s, store in enumerate(stores) if not store_ids or store in store_ids]
                units = units[keep].transpose(1, 0, 3, 2)  # (W, S, k, G)
                n_weeks, n_stores, n_skus, n_segments = units.shape
                frames.append(
                    pd.DataFrame(
                        {
                            "week_id": np.repeat(weeks, n_stores * n_skus * n_segments),
                            "store_id": np.tile(
                                np.repeat([stores[s] for s in keep], n_skus * n_segments), n_weeks
                            ),
                            "sku_id": np.tile(np.repeat(skus, n_segments), n_weeks * n_stores),
                            "segment": np.tile(SEGMENT_NAMES, n_weeks * n_stores * n_skus),
                            "units": units.ravel(),
                        }
                    )
                )
        if not frames:
            return pd.DataFrame(columns=BASELINE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def _paths(self, options: Sequence[PlanLine]) -> list[_Path]:
        return [self._path(line) for line in options]

    def _path(self, line: PlanLine) -> _Path:
        skus = line.skus
        for sku_id in skus:
            if sku_id not in self._reference:
                raise ValueError(f"unknown SKU {sku_id}")
        if line.region not in self._regions:
            raise ValueError(f"no stores in {line.region}")
        if line.start_week < self.as_of_week:
            raise ValueError(
                f"{line.sku_id} in {line.region} starts in week {line.start_week}, "
                f"before the as-of week {self.as_of_week}"
            )
        if line.start_week + line.duration_weeks > self._total_weeks:
            raise ValueError(f"{line.sku_id} in {line.region} runs past the calendar")
        length = min(line.duration_weeks + self._after, self._total_weeks - line.start_week)
        reference = np.array([self._reference[sku_id] for sku_id in skus])
        prices = np.tile(reference, (length, len(SEGMENTS), 1))
        mechanisms = np.full(prices.shape, -1)
        promo = slice(0, line.duration_weeks)
        targeted = _segments(line.target_segment)
        for k, price in enumerate(reference):
            prices[promo, targeted, k] = effective_unit_price(line.mechanism, price, line.depth_pct)
        mechanisms[promo, targeted, 0] = MECHANISMS.index(line.mechanism)
        units = self._demand.expected_units(
            line.region, line.start_week, prices, mechanisms, sku_ids=skus
        )
        size = np.array([self._size[sku_id] for sku_id in skus])
        return _Path(
            line=line,
            units=units.sum(axis=0),
            variance=(units + units**2 / size).sum(axis=0),
            baseline=self._unpromoted(line.region, line.start_week, length, skus).sum(axis=0),
            prices=prices,
            reference=reference,
            costs=np.array([self._cost[sku_id] for sku_id in skus]),
        )

    def _unpromoted(self, region: Region, start: int, length: int, skus: Sequence[str]) -> Array:
        """Per store (S, W, G, k): the SKUs' expected units with no promotion."""
        key = (region, start, length, tuple(skus))
        cached = self._baselines.get(key)
        if cached is None:
            reference = np.array([self._reference[sku_id] for sku_id in skus])
            prices = np.tile(reference, (length, len(SEGMENTS), 1))
            cached = self._demand.expected_units(
                region, start, prices, np.full(prices.shape, -1), sku_ids=list(skus)
            )
            self._baselines[key] = cached
        return cached


class TrueRelations:
    """`promopilot.models.relations.Relations`' `substitutes` and `complements`, from the true
    pairs. A partner's theta is the true effect of the SKU's log price ratio on the partner's
    log units, which is what promoting the SKU does to it; std_error and q_value are 0."""

    def __init__(self, truth: GroundTruth) -> None:
        self._theta = {(e.sku_id, e.other_sku_id): e.theta for e in truth.cross_effects}
        self._pairs = {"substitute": truth.substitute_pairs, "complement": truth.complement_pairs}

    def substitutes(self, sku_id: str) -> pd.DataFrame:
        """sku_id, theta, std_error, q_value; the strongest first."""
        partners = self._partners(sku_id, "substitute").assign(q_value=0.0)
        partners = partners.sort_values(["theta", "sku_id"], ascending=[False, True])
        return partners[["sku_id", "theta", "std_error", "q_value"]].reset_index(drop=True)

    def complements(self, sku_id: str) -> pd.DataFrame:
        """sku_id, lift, support, theta, std_error; the strongest (most negative theta) first.
        The true world has no basket lift, so lift and support are NaN."""
        partners = self._partners(sku_id, "complement").assign(lift=np.nan, support=np.nan)
        partners = partners.sort_values(["theta", "sku_id"], ascending=[True, True])
        return partners[["sku_id", "lift", "support", "theta", "std_error"]].reset_index(drop=True)

    def _partners(self, sku_id: str, kind: str) -> pd.DataFrame:
        others = [b if a == sku_id else a for a, b in self._pairs[kind] if sku_id in (a, b)]
        return pd.DataFrame(
            {
                "sku_id": pd.Series(others, dtype=object),
                "theta": pd.Series(
                    [self._theta.get((other, sku_id), 0.0) for other in others], dtype=float
                ),
                "std_error": pd.Series(0.0, index=range(len(others)), dtype=float),
            }
        )


def _segments(target: TargetSegment) -> list[int]:
    if target is TargetSegment.ALL_CUSTOMERS:
        return list(range(len(SEGMENTS)))
    return [SEGMENT_NAMES.index(target.value)]
