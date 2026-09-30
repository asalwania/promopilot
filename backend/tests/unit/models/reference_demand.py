"""A frozen copy of the demand model's prediction pipeline as it was before #113 (ADR 0087).

The test oracle for the faster pipeline: every number `DemandModel.predict`, `line_paths` and
`response_rows` return must equal this copy's bit for bit. It reads the fitted model's private
parts, as only a test may. Do not edit it to follow the production code.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from promopilot.domain import Mechanism, PlanLine, TargetSegment
from promopilot.economics import (
    effective_unit_price,
    fixed_marketing_cost,
    gross_profit,
    incremental_profit,
)
from promopilot.models.demand import (
    KEYS,
    OPTION_COLUMNS,
    PULL_FORWARD_WEEKS,
    RESPONSE_ROW_COLUMNS,
    SEGMENTS,
    SERIES,
    DemandModel,
    Prediction,
    PredictionContext,
    ResponseRows,
)
from promopilot.models.response import TERM_NAMES, PromoResponse, design


def _baseline_predict(
    baseline: Any, keys: pd.DataFrame, *, competitor_index: np.ndarray | None = None
) -> np.ndarray:
    distinct = keys.reset_index(drop=True)
    if competitor_index is not None:
        distinct = distinct.assign(competitor_index=competitor_index)
    group = distinct.groupby(list(distinct.columns), sort=False, dropna=False).ngroup().to_numpy()
    first = np.unique(group, return_index=True)[1]
    unique = distinct.iloc[first].reset_index(drop=True)
    features = baseline.features.build(unique[keys.columns])
    if competitor_index is not None:
        features["competitor_index"] = unique["competitor_index"].to_numpy()
    return np.asarray(baseline.booster.predict(features), dtype=float)[group]


def _matrix(model: PromoResponse, column: str, rows: pd.DataFrame) -> np.ndarray:
    return np.asarray(model.wide(column).loc[rows["sku_id"]].to_numpy(dtype=float))


def _variance(
    model: PromoResponse, rows: pd.DataFrame, means: np.ndarray, groups: np.ndarray
) -> np.ndarray:
    size = int(groups.max()) + 1 if len(groups) else 0
    noise = means + means**2 / model.dispersion.loc[rows["sku_id"]].to_numpy()
    pairs, pair_index = np.unique(
        np.column_stack([groups, pd.factorize(rows["sku_id"])[0]]), axis=0, return_inverse=True
    )
    gradient = np.zeros((len(pairs), len(TERM_NAMES)))
    np.add.at(gradient, pair_index.ravel(), design(rows) * means[:, None])
    first = np.unique(pair_index.ravel(), return_index=True)[1]
    errors = _matrix(model, "std_error", rows.iloc[first])
    parameter = ((gradient * errors) ** 2).sum(axis=1)
    return np.asarray(
        np.bincount(pairs[:, 0], weights=parameter, minlength=size)
        + np.bincount(groups, weights=noise, minlength=size)
    )


def _log_effect(model: PromoResponse, rows: pd.DataFrame) -> np.ndarray:
    return np.asarray((design(rows) * _matrix(model, "estimate", rows)).sum(axis=1))


class Reference:
    """The pre-#113 `_Response` prediction methods, over a fitted model's parts."""

    def __init__(self, model: DemandModel) -> None:
        response = model._response
        self.model = response.model
        self.as_of_week = response.as_of_week
        self.last_week = response.last_week
        self.products = response.products
        self.stores = response.stores
        self.competitors = response.competitors
        self._baseline_model = model._baseline

    def predict(self, lines: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        options = list(lines)
        rows, promoted, unpromoted = self._paths(options, context)
        base_price = rows["base_price"].to_numpy()
        unit_cost = self.products["unit_cost"].reindex(rows["sku_id"]).to_numpy()
        price = rows["price"].to_numpy()
        option = rows["promo"].to_numpy()
        anchor = rows["anchor"].to_numpy(dtype=bool)
        in_promo = (rows["week_id"] < rows["start_week"] + rows["duration"]).to_numpy()

        def total(values: np.ndarray, where: np.ndarray) -> np.ndarray:
            return np.bincount(option[where], weights=values[where], minlength=len(options))

        counted = anchor & in_promo
        units = total(promoted, counted)
        revenue = total(promoted * price, in_promo)
        profit = total(gross_profit(promoted, price, unit_cost), in_promo)
        fixed: Any = np.array(
            [
                fixed_marketing_cost(line.mechanism, line.duration_weeks, context.policy)
                for line in options
            ]
        )
        partner = ~anchor & in_promo

        def std(where: np.ndarray) -> np.ndarray:
            variance = _variance(self.model, rows[where], promoted[where], option[where])
            return np.sqrt(np.pad(variance, (0, len(options) - len(variance))))

        discount = (base_price - price) * promoted
        table = pd.DataFrame(
            {
                "units": units,
                "units_std": std(counted),
                "baseline_units": total(unpromoted, counted),
                "pull_forward_units": total(unpromoted - promoted, anchor & ~in_promo),
                "incremental_units": total(promoted - unpromoted, anchor),
                "revenue": revenue,
                "gross_profit": profit,
                "margin": np.divide(profit, revenue, out=np.zeros_like(profit), where=revenue > 0),
                "promo_cost": total(discount, in_promo) + fixed,
                "incremental_profit": incremental_profit(
                    total(gross_profit(promoted, price, unit_cost), np.full(len(rows), True)),
                    total(
                        gross_profit(unpromoted, base_price, unit_cost), np.full(len(rows), True)
                    ),
                    fixed,
                ),
                "anchor_discount_funding": total(discount, counted),
                "partner_units": total(promoted, partner),
                "partner_units_std": std(partner),
                "partner_baseline_units": total(unpromoted, partner),
                "partner_discount_funding": total(discount, partner),
            },
            columns=OPTION_COLUMNS,
        )
        return Prediction(
            options=table,
            segments=self._by_segment(rows[counted], promoted[counted], unpromoted[counted]),
        )

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        rows, promoted, unpromoted = self._paths(list(options), context)
        paths = rows[["promo", "week_id", "sku_id", "segment", "price"]].assign(
            units=promoted, baseline_units=unpromoted
        )
        paths = paths.groupby(["promo", "week_id", "sku_id", "segment"], sort=True).agg(
            units=("units", "sum"),
            baseline_units=("baseline_units", "sum"),
            price=("price", "first"),
        )
        result: pd.DataFrame = paths.reset_index().rename(columns={"promo": "option"})
        return result

    def response_rows(
        self, options: Sequence[PlanLine], context: PredictionContext
    ) -> ResponseRows:
        rows, store_baseline = self._rows(list(options), context)
        in_promo = (rows["week_id"] < rows["start_week"] + rows["duration"]).to_numpy()
        rows = rows[in_promo].reset_index(drop=True)
        sku_ids = sorted(set(rows["sku_id"]))
        table = rows.rename(columns={"promo": "option"}).assign(
            unit_cost=self.products["unit_cost"].reindex(rows["sku_id"]).to_numpy(),
            baseline_units=store_baseline[in_promo],
        )
        return ResponseRows(
            rows=table[RESPONSE_ROW_COLUMNS],
            design=pd.DataFrame(design(rows), columns=TERM_NAMES),
            estimate=self.model.wide("estimate").loc[sku_ids],
            std_error=self.model.wide("std_error").loc[sku_ids],
            dispersion=self.model.dispersion.loc[sku_ids].astype(float),
        )

    def _paths(
        self, options: list[PlanLine], context: PredictionContext
    ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        rows, store_baseline = self._rows(options, context)
        plain = _with_ratios(
            rows.assign(price=rows["base_price"], mechanism=None, pull_forward_share=0.0)
        )
        promoted = store_baseline * np.exp(_log_effect(self.model, rows))
        unpromoted = store_baseline * np.exp(_log_effect(self.model, plain))
        return rows, promoted, unpromoted

    def _rows(
        self, options: list[PlanLine], context: PredictionContext
    ) -> tuple[pd.DataFrame, np.ndarray]:
        regions = set(self.stores["region"])
        for line in options:
            for sku_id in line.skus:
                if sku_id not in self.products.index:
                    raise ValueError(f"unknown SKU {sku_id}")
            if line.region not in regions:
                raise ValueError(f"no stores in {line.region}")
            if line.start_week < self.as_of_week:
                raise ValueError(
                    f"{line.sku_id} in {line.region} starts in week {line.start_week}, "
                    f"before the as-of week {self.as_of_week}"
                )
            if line.start_week + line.duration_weeks > self.last_week + 1:
                raise ValueError(f"{line.sku_id} in {line.region} runs past the calendar")
        promotions = _as_promotions(options)
        exposure = _exposure(promotions, self.products)
        rows = exposure[["promo", "region", "sku_id", "anchor"]].drop_duplicates()
        rows = rows.merge(promotions[["start_week", "duration"]], left_on="promo", right_index=True)
        rows["week_id"] = [
            list(range(start, min(start + duration + PULL_FORWARD_WEEKS, self.last_week + 1)))
            for start, duration in zip(rows["start_week"], rows["duration"], strict=True)
        ]
        rows = rows.explode("week_id").astype({"week_id": int})
        rows = rows.merge(self.stores, on="region")
        rows = rows.merge(pd.DataFrame({"segment": SEGMENTS}), how="cross")
        rows = _priced(rows, exposure, ["promo", *SERIES], self.products)
        rows = _with_reference(rows, self._competitors(context))
        rows["competitor_price"] = rows["competitor_price"].fillna(rows["base_price"])
        rows = _with_ratios(rows)
        store_baseline = _baseline_predict(
            self._baseline_model, rows[KEYS], competitor_index=rows["reference_index"].to_numpy()
        )
        return rows, store_baseline

    def _by_segment(
        self, rows: pd.DataFrame, promoted: np.ndarray, unpromoted: np.ndarray
    ) -> pd.DataFrame:
        segment = rows["segment"].map({name: g for g, name in enumerate(SEGMENTS)}).to_numpy()
        groups = rows["promo"].to_numpy() * len(SEGMENTS) + segment
        size = int(groups.max()) + 1 if len(groups) else 0
        return pd.DataFrame(
            {
                "option": np.arange(size) // len(SEGMENTS),
                "segment": [SEGMENTS[g % len(SEGMENTS)] for g in range(size)],
                "units": np.bincount(groups, weights=promoted, minlength=size),
                "units_std": np.sqrt(_variance(self.model, rows, promoted, groups)),
                "baseline_units": np.bincount(groups, weights=unpromoted, minlength=size),
            }
        )

    def _competitors(self, context: PredictionContext) -> pd.DataFrame:
        competitors = self.competitors.copy()
        for (region, sku_id), price in context.competitor_prices.items():
            competitors.loc[(region.value, sku_id), "competitor_price"] = price
        return competitors


def _as_promotions(options: list[PlanLine]) -> pd.DataFrame:
    """Promo options as rows shaped like the promotions history, one per option."""
    return pd.DataFrame(
        [
            {
                "sku_id": line.sku_id,
                "region": line.region.value,
                "mechanism": line.mechanism.value,
                "depth": line.depth_pct,
                "start_week": line.start_week,
                "duration": line.duration_weeks,
                "target_segment": line.target_segment.value,
                "bundle_sku_id": line.bundle_partner_sku_id,
            }
            for line in options
        ],
        columns=[
            "sku_id",
            "region",
            "mechanism",
            "depth",
            "start_week",
            "duration",
            "target_segment",
            "bundle_sku_id",
        ],
    )


def _priced(
    rows: pd.DataFrame, exposure: pd.DataFrame, series: list[str], products: pd.DataFrame
) -> pd.DataFrame:
    """Adds the price each row paid, the mechanism that applied and the pull-forward share."""
    keys = [*series, "week_id"]
    rows = rows.merge(
        exposure[[*keys, "price", "mechanism"]].drop_duplicates(keys), on=keys, how="left"
    )
    rows = rows.merge(_pull_forward_share(exposure, series), on=keys, how="left")
    rows["base_price"] = products["base_price"].reindex(rows["sku_id"]).to_numpy()
    return rows.fillna({"price": rows["base_price"], "pull_forward_share": 0.0})


def _with_reference(rows: pd.DataFrame, competitors: pd.DataFrame) -> pd.DataFrame:
    """Adds each series' competitor columns; with no competitor history the index is 1."""
    rows = rows.merge(competitors, left_on=["region", "sku_id"], right_index=True, how="left")
    return rows.fillna({"reference_index": 1.0}).reset_index(drop=True)


def _with_ratios(rows: pd.DataFrame) -> pd.DataFrame:
    """The response model's price terms (ADR 0016): log(p / p_ref), and log(cp / p) measured
    from the series' reference index, where the baseline is read off (ADR 0024)."""
    return rows.assign(
        log_price_ratio=np.log(rows["price"] / rows["base_price"]),
        log_competitor_ratio=np.log(rows["competitor_price"] / rows["price"])
        - np.log(rows["reference_index"]),
    )


def _exposure(promotions: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """Every promo week, region, SKU and segment a promotion prices, with price and mechanism.

    The mechanism's own effect applies to the anchor only; a bundle partner just gets the
    lower price (ADR 0016).
    """
    weeks = _promo_weeks(promotions)
    details = promotions[["mechanism", "depth"]].reset_index(drop=True)
    weeks = weeks.join(details, on="promo")
    weeks["base_price"] = products["base_price"].reindex(weeks["sku_id"]).to_numpy()
    base_price = weeks["base_price"].to_numpy(dtype=float)
    price = base_price.copy()
    for mechanism, depth in set(zip(weeks["mechanism"], weeks["depth"], strict=True)):
        at = ((weeks["mechanism"] == mechanism) & (weeks["depth"] == depth)).to_numpy()
        price[at] = effective_unit_price(Mechanism(mechanism), base_price[at], int(depth))
    weeks["price"] = price
    weeks["mechanism"] = weeks["mechanism"].where(weeks["anchor"])
    return weeks.drop(columns=["depth", "base_price"])


def _pull_forward_share(exposure: pd.DataFrame, series: list[str]) -> pd.DataFrame:
    """The share of the previous four weeks each series was promoted (ADR 0016)."""
    promoted = exposure[[*series, "week_id"]].drop_duplicates()
    later = pd.concat(
        [promoted.assign(week_id=promoted["week_id"] + k) for k in range(1, PULL_FORWARD_WEEKS + 1)]
    )
    share = later.groupby([*series, "week_id"]).size() / PULL_FORWARD_WEEKS
    return share.rename("pull_forward_share").reset_index()


def _promo_weeks(promotions: pd.DataFrame) -> pd.DataFrame:
    """promo (row position), region, SKU, segment and week each promotion prices.

    A bundle cuts its partner's price too (ADR 0016); `anchor` tells the two apart.
    """
    columns = ["promo", "week_id", *SERIES, "anchor"]
    if promotions.empty:
        return pd.DataFrame(columns=columns).astype({"week_id": int, "anchor": bool})
    touched = pd.DataFrame(
        {
            "promo": np.arange(len(promotions)),
            "region": promotions["region"].to_numpy(),
            "week_id": [
                list(range(start, start + duration))
                for start, duration in zip(
                    promotions["start_week"], promotions["duration"], strict=True
                )
            ],
            "segment": [
                SEGMENTS if target == TargetSegment.ALL_CUSTOMERS else [target]
                for target in promotions["target_segment"]
            ],
            "sku_id": [
                [(sku, True)] if pd.isna(partner) else [(sku, True), (partner, False)]
                for sku, partner in zip(
                    promotions["sku_id"], promotions["bundle_sku_id"], strict=True
                )
            ],
        }
    )
    touched = touched.explode("week_id").explode("segment").explode("sku_id")
    touched["anchor"] = [anchor for _, anchor in touched["sku_id"]]
    touched["sku_id"] = [sku for sku, _ in touched["sku_id"]]
    return touched[columns].astype({"week_id": int, "anchor": bool}).reset_index(drop=True)
