"""The demand model (SPEC §9.1): a baseline forecast, then the promo response on top of it.

Stage one, the baseline: a LightGBM model on the SPEC §9.1 features forecasts units per
store x SKU x segment x week with no promotion. It is fitted only on clean weeks: no
promotion for that SKU and segment in the week or the four weeks before it, so neither promo
uplift nor the pull-forward dip leaks into the baseline (ADR 0023).

Stage two, the promo response (`promopilot.models.response`): per-SKU elasticities,
competitor sensitivity, mechanism effects and pull-forward, fitted on every week against the
baseline forecast at a neutral competitor price (ADR 0024).

Every fit sees only history strictly before the as-of week (ADR 0008).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, Region, Segment, TargetSegment
from promopilot.economics import (
    effective_unit_price,
    fixed_marketing_cost,
    gross_profit,
    incremental_profit,
)
from promopilot.models.response import TERM_NAMES, TERMS, PromoResponse, design

HOLDOUT_WEEKS = 12
"""Baseline WAPE is measured on the last 12 weeks before the as-of week (SPEC §9.1)."""

PULL_FORWARD_WEEKS = 4
"""Weeks after a promotion that carry its post-promo dip (ADR 0016)."""

SEASON_DAYS = 365.25
SEGMENTS = [segment.value for segment in Segment]
KEYS = ["week_id", "store_id", "sku_id", "segment"]
WAPE_GRAINS = {
    "": KEYS,
    "_store_sku": ["week_id", "store_id", "sku_id"],
    "_region_sku": ["week_id", "region", "sku_id"],
}
"""Holdout WAPE is reported at the model grain and summed to store and region (ADR 0023)."""

CATEGORICAL = ["segment", "region", "category", "subcategory", "holiday_name"]
FEATURES = [
    *CATEGORICAL,
    "base_price",
    "is_kvi",
    "log_level",
    "lag_52",
    "holiday_intensity",
    "next_holiday_intensity",
    "season_sin",
    "season_cos",
    "competitor_index",
]
NO_HOLIDAY = "none"

LIGHTGBM_PARAMS: dict[str, object] = {
    "objective": "poisson",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}
BOOSTING_ROUNDS = 300


@dataclass(frozen=True)
class DemandHistory:
    """The data tables a demand fit reads, as the as-of-week repositories return them."""

    products: pd.DataFrame
    stores: pd.DataFrame
    calendar: pd.DataFrame
    sales_weekly: pd.DataFrame
    promotions_history: pd.DataFrame
    competitor_prices: pd.DataFrame

    def before(self, week: int) -> "DemandHistory":
        """What is visible at the start of `week`; the calendar is known in advance."""
        promotions = self.promotions_history
        promotions = promotions[promotions["start_week"] < week].copy()
        promotions["duration"] = np.minimum(promotions["duration"], week - promotions["start_week"])
        sales = self.sales_weekly
        competitors = self.competitor_prices
        return replace(
            self,
            sales_weekly=sales[sales["week_id"] < week],
            promotions_history=promotions,
            competitor_prices=competitors[competitors["week_id"] < week],
        )


@dataclass(frozen=True)
class PredictionContext:
    """What a prediction needs beyond the promo options themselves."""

    policy: CompanyPolicy = field(default_factory=CompanyPolicy)
    competitor_prices: Mapping[tuple[Region, str], float] = field(default_factory=dict)
    """Competitor price per (region, SKU) over the promo; by default the last one known."""


OPTION_COLUMNS = [
    "units",
    "units_std",
    "baseline_units",
    "pull_forward_units",
    "incremental_units",
    "revenue",
    "gross_profit",
    "margin",
    "promo_cost",
    "incremental_profit",
    "anchor_discount_funding",
    "partner_units",
    "partner_units_std",
    "partner_baseline_units",
    "partner_discount_funding",
]


FITTED_COLUMNS = [
    "week_id",
    "region",
    "sku_id",
    "segment",
    "units",
    "fitted_units",
    "log_price_ratio",
]


@dataclass(frozen=True)
class Prediction:
    """Predicted outcomes of promo options, each as if it ran alone, summed over the region.

    The fields mean what the oracle's line outcomes mean (ADR 0011): units, baseline_units
    and units_std are the anchor SKU's over the promo weeks; pull_forward_units is its dip in
    the weeks after; incremental_units is the uplift net of that dip. Revenue, gross profit,
    margin and promo cost cover the promo weeks and include a BUNDLE's partner;
    incremental_profit also covers the pull-forward weeks and is net of the fixed marketing
    cost. Cross effects on other SKUs are left to the relations model (E5).

    The partner_* columns are a BUNDLE partner's own units (mean, std and baseline over the
    promo weeks) and discount funding; 0 for other mechanisms. Discount funding is split per
    SKU, each at the depth off its own base price: the pair's discount pro-rata by base price
    (ADR 0005, ADR 0014). anchor_discount_funding + partner_discount_funding + the fixed
    marketing cost is promo_cost.
    """

    options: pd.DataFrame
    """One row per option, in input order: OPTION_COLUMNS."""
    segments: pd.DataFrame
    """One row per option and segment: option, segment, units, units_std, baseline_units."""


COMPETITOR_TERM = TERM_NAMES[TERMS.index(("gamma", None))]
"""The design column of the competitor term gamma: log(cp / p) - log r, where cp is the
competitor's price, p the price the row pays and r the series' reference index (ADR 0024)."""

RESPONSE_ROW_COLUMNS = [
    "option",
    "sku_id",
    "anchor",
    "store_id",
    "segment",
    "week_id",
    "price",
    "base_price",
    "unit_cost",
    "baseline_units",
]


@dataclass(frozen=True)
class ResponseRows:
    """What sampling promo options' demand needs, per store, segment and promo week (ADR 0042).

    A row's expected units are baseline_units x exp(Σ_t design[t] x term[t]), with the terms
    of its SKU; `predict`'s units are these summed at the estimates. The simulator samples
    the terms from N(estimate, std_error) and the units from a negative binomial of the SKU's
    size around that mean (ADR 0024).
    """

    rows: pd.DataFrame
    """One row per option, SKU (the anchor, and a BUNDLE's partner), store, segment and promo
    week: RESPONSE_ROW_COLUMNS. `option` is the option's position in the input, `anchor` tells
    the anchor from the partner, and baseline_units is the store's unpromoted baseline at the
    series' reference competitor index."""
    design: pd.DataFrame
    """Each row's covariate for each term, aligned with `rows`; columns are term names, the
    competitor term's being COMPETITOR_TERM."""
    estimate: pd.DataFrame
    """Per SKU (the index) and term (the columns): the fitted estimate."""
    std_error: pd.DataFrame
    """Per SKU and term: the estimate's standard error."""
    dispersion: pd.Series
    """Per SKU: the negative binomial size of store-level demand noise."""


@dataclass(frozen=True)
class DemandModel:
    as_of_week: int
    metrics: dict[str, float]
    _baseline: "_Baseline"
    _response: "_Response"

    def coefficients(self) -> pd.DataFrame:
        """The promo response terms per SKU: sku_id, parameter, level, estimate, std_error.

        parameter is alpha (baseline recalibration), beta (own-price elasticity; level is the
        segment), gamma (competitor sensitivity), mu (mechanism effect; level is the
        mechanism) or phi (pull-forward), after shrinkage toward the subcategory.
        """
        return self._response.model.coefficients.copy()

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        """Mean and std of each promo option's units, and its economics (ADR 0005).

        Raises ValueError for an option the model cannot predict: an unknown SKU or bundle
        partner, a region with no stores, a start before the as-of week, or weeks past the
        calendar.
        """
        return self._response.predict(list(options), context, self._baseline)

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        """`predict` broken down: each option's SKUs per week, SKU and segment, over its region.

        One row per option, week (the promo weeks and the pull-forward weeks after them), SKU
        (the anchor and a BUNDLE's partner) and segment: units promoted, baseline_units with
        no promotion, and the price paid. The anchor's units and baseline_units over the promo
        weeks sum to `predict`'s. Pairwise cannibalisation reads these (ADR 0033).
        """
        return self._response.line_paths(list(options), context, self._baseline)

    def response_rows(
        self, options: Sequence[PlanLine], context: PredictionContext
    ) -> ResponseRows:
        """The terms, covariates and baselines behind each option's promo-week units.

        Raises ValueError for an option `predict` cannot predict.
        """
        return self._response.response_rows(list(options), context, self._baseline)

    def fitted_history(self, history: DemandHistory) -> pd.DataFrame:
        """The model's in-sample fit: FITTED_COLUMNS per region x SKU x segment x week.

        Covers the history before the model's as-of week. fitted_units is the fitted mean
        (the baseline times the promo response), and log_price_ratio is log(p / p_ref) for
        the price that row paid. The relations model regresses cross effects on these.
        """
        return self._response.fitted(history.before(self.as_of_week), self._baseline)

    def baseline(
        self,
        weeks: Iterable[int],
        *,
        regions: Sequence[str] | None = None,
        store_ids: Sequence[str] | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """No-promotion units for every store x SKU x segment in the given weeks."""
        return self._baseline.forecast(
            list(weeks), regions=regions, store_ids=store_ids, sku_ids=sku_ids
        )


def fit(history: DemandHistory, as_of_week: int, seed: int) -> DemandModel:
    visible = history.before(as_of_week)
    split = as_of_week - HOLDOUT_WEEKS
    validation = _Baseline.fit(visible.before(split), end=split, seed=seed)
    holdout = _clean_segment_sales(visible)
    holdout = holdout[holdout["week_id"] >= split]
    holdout = holdout.assign(predicted=validation.predict(holdout[KEYS]))
    holdout = holdout.merge(visible.stores[["store_id", "region"]], on="store_id")
    baseline = _Baseline.fit(visible, end=as_of_week, seed=seed)
    response = _Response.fit(visible, baseline)
    coefficients = response.model.coefficients
    return DemandModel(
        as_of_week=as_of_week,
        metrics={
            # Plan lines are region-level (ADR 0004); segment-level counts are mostly noise.
            **{
                f"baseline_wape{suffix}": _grain_wape(
                    holdout.groupby(grain)[["units", "predicted"]].sum()
                )
                for suffix, grain in WAPE_GRAINS.items()
            },
            "response_skus_fitted": float(response.model.fitted_skus),
            "elasticity_median_std_error": float(
                coefficients.loc[coefficients["parameter"] == "beta", "std_error"].median()
            ),
        },
        _baseline=baseline,
        _response=response,
    )


def wape(units: Sequence[float] | pd.Series, predicted: Sequence[float] | pd.Series) -> float:
    """Weighted absolute percentage error: the absolute errors summed over the units summed.

    Raises ValueError when there are no units to weigh the errors by.
    """
    actual = np.asarray(units, dtype=float)
    total = actual.sum()
    if total <= 0:
        raise ValueError("WAPE is undefined with no units")
    return float(np.abs(np.asarray(predicted, dtype=float) - actual).sum() / total)


def _grain_wape(frame: pd.DataFrame) -> float:
    return wape(frame["units"], frame["predicted"])


@dataclass(frozen=True)
class _Baseline:
    booster: lgb.Booster
    features: "_Features"

    @classmethod
    def fit(cls, history: DemandHistory, *, end: int, seed: int) -> "_Baseline":
        clean = _clean_segment_sales(history)
        features = _Features.of(history, clean, end=end)
        dataset = lgb.Dataset(
            features.build(clean[KEYS]),
            label=clean["units"].to_numpy(),
            categorical_feature=CATEGORICAL,
        )
        booster = lgb.train({**LIGHTGBM_PARAMS, "seed": seed}, dataset, BOOSTING_ROUNDS)
        return cls(booster=booster, features=features)

    def forecast(
        self,
        weeks: list[int],
        *,
        regions: Sequence[str] | None,
        store_ids: Sequence[str] | None,
        sku_ids: Sequence[str] | None,
    ) -> pd.DataFrame:
        unknown = set(weeks) - set(self.features.calendar["week_id"])
        if unknown:
            raise ValueError(f"weeks outside the calendar: {sorted(unknown)}")
        stores = self.features.stores
        if regions is not None:
            stores = stores[stores["region"].isin(regions)]
        if store_ids is not None:
            stores = stores[stores["store_id"].isin(store_ids)]
        skus = self.features.products["sku_id"]
        if sku_ids is not None:
            skus = skus[skus.isin(sku_ids)]
        grid = pd.MultiIndex.from_product(
            [weeks, stores["store_id"], skus, SEGMENTS], names=KEYS
        ).to_frame(index=False)
        return grid.assign(units=self.predict(grid))

    def predict(
        self, keys: pd.DataFrame, *, competitor_index: np.ndarray | None = None
    ) -> np.ndarray:
        """Units for each key, optionally at a given competitor price index per key.

        Each distinct key (and index) is forecast once: a batch of promo options repeats the
        same store x SKU x segment weeks many times over (ADR 0035).
        """
        distinct = keys.reset_index(drop=True)
        if competitor_index is not None:
            distinct = distinct.assign(competitor_index=competitor_index)
        group = (
            distinct.groupby(list(distinct.columns), sort=False, dropna=False).ngroup().to_numpy()
        )
        first = np.unique(group, return_index=True)[1]
        unique = distinct.iloc[first].reset_index(drop=True)
        features = self.features.build(unique[keys.columns])
        if competitor_index is not None:
            features["competitor_index"] = unique["competitor_index"].to_numpy()
        return np.asarray(self.booster.predict(features), dtype=float)[group]


@dataclass(frozen=True)
class _Features:
    """The history snapshot baseline features are built from, for any calendar week."""

    end: int
    stores: pd.DataFrame
    products: pd.DataFrame
    calendar: pd.DataFrame
    levels: pd.DataFrame
    clean_units: pd.DataFrame
    competitor_index: pd.DataFrame
    categories: dict[str, list[str]]

    @classmethod
    def of(cls, history: DemandHistory, clean: pd.DataFrame, *, end: int) -> "_Features":
        levels = (
            clean.groupby(["store_id", "sku_id", "segment"])["units"]
            .mean()
            .rename("level")
            .reset_index()
        )
        calendar = _calendar_features(history.calendar)
        prices = history.competitor_prices.merge(
            history.products[["sku_id", "base_price"]], on="sku_id"
        )
        prices["competitor_index"] = prices["competitor_price"] / prices["base_price"]
        return cls(
            end=end,
            stores=history.stores[["store_id", "region"]],
            products=history.products[
                ["sku_id", "category", "subcategory", "base_price", "is_kvi"]
            ],
            calendar=calendar,
            levels=levels,
            clean_units=clean[[*KEYS, "units"]],
            competitor_index=prices[["week_id", "region", "sku_id", "competitor_index"]],
            categories={
                "segment": SEGMENTS,
                "region": sorted(history.stores["region"].unique()),
                "category": sorted(history.products["category"].unique()),
                "subcategory": sorted(history.products["subcategory"].unique()),
                "holiday_name": sorted(calendar["holiday_name"].unique()),
            },
        )

    def build(self, keys: pd.DataFrame) -> pd.DataFrame:
        frame = keys.reset_index(drop=True).merge(self.stores, on="store_id", how="left")
        frame = frame.merge(self.products, on="sku_id", how="left")
        frame = frame.merge(self.calendar, on=["week_id", "region"], how="left")
        frame = frame.merge(self.levels, on=["store_id", "sku_id", "segment"], how="left")
        frame["log_level"] = np.log1p(frame["level"])
        last_year = self.clean_units.assign(week_id=self.clean_units["week_id"] + 52)
        frame = frame.merge(last_year.rename(columns={"units": "lag_52"}), on=KEYS, how="left")
        # Future competitor prices are unknown: carry the last known index forward (ADR 0023).
        frame["price_week"] = np.minimum(frame["week_id"], self.end - 1)
        frame = frame.merge(
            self.competitor_index.rename(columns={"week_id": "price_week"}),
            on=["price_week", "region", "sku_id"],
            how="left",
        )
        for column, categories in self.categories.items():
            frame[column] = pd.Categorical(frame[column], categories=categories)
        frame["is_kvi"] = frame["is_kvi"].astype(float)
        return frame[FEATURES]


SERIES = ["region", "sku_id", "segment"]
"""A promo response series: plan lines and promotions are region-level (ADR 0004)."""


@dataclass(frozen=True)
class _Response:
    """The fitted promo response plus what predicting with it needs from the history."""

    model: PromoResponse
    as_of_week: int
    last_week: int
    products: pd.DataFrame
    """Indexed by sku_id: subcategory, base_price, unit_cost."""
    stores: pd.DataFrame
    competitors: pd.DataFrame
    """Per region and SKU: the reference competitor index (the series' median, where the
    baseline is read off) and the last competitor price known before the as-of week."""

    @classmethod
    def fit(cls, history: DemandHistory, baseline: _Baseline) -> "_Response":
        products = history.products.set_index("sku_id")[["subcategory", "base_price", "unit_cost"]]
        prices = history.competitor_prices[["week_id", "region", "sku_id", "competitor_price"]]
        index = prices["competitor_price"] / products["base_price"].reindex(prices["sku_id"]).values
        by_series = prices.assign(index=index).sort_values("week_id").groupby(["region", "sku_id"])
        competitors = pd.DataFrame(
            {
                "reference_index": by_series["index"].median(),
                "competitor_price": by_series["competitor_price"].last(),
            }
        )
        rows = _history_rows(history, baseline, competitors, products)
        return cls(
            model=PromoResponse.fit(
                rows, {str(sku): str(sub) for sku, sub in products["subcategory"].items()}
            ),
            as_of_week=baseline.features.end,
            last_week=int(history.calendar["week_id"].max()),
            products=products,
            stores=history.stores[["store_id", "region"]],
            competitors=competitors,
        )

    def fitted(self, history: DemandHistory, baseline: _Baseline) -> pd.DataFrame:
        rows = _history_rows(history, baseline, self.competitors, self.products)
        rows["fitted_units"] = np.exp(rows["offset"] + self.model.log_effect(rows))
        return rows[FITTED_COLUMNS].sort_values(FITTED_COLUMNS[:4], ignore_index=True)

    def line_paths(
        self, options: list[PlanLine], context: PredictionContext, baseline: _Baseline
    ) -> pd.DataFrame:
        rows, promoted, unpromoted = self._paths(options, context, baseline)
        paths = rows[["promo", "week_id", "sku_id", "segment", "price"]].assign(
            units=promoted, baseline_units=unpromoted
        )
        paths = paths.groupby(["promo", "week_id", "sku_id", "segment"], sort=True).agg(
            units=("units", "sum"),
            baseline_units=("baseline_units", "sum"),
            price=("price", "first"),
        )
        return paths.reset_index().rename(columns={"promo": "option"})

    def response_rows(
        self, options: list[PlanLine], context: PredictionContext, baseline: _Baseline
    ) -> ResponseRows:
        rows, store_baseline = self._rows(options, context, baseline)
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

    def predict(
        self, options: list[PlanLine], context: PredictionContext, baseline: _Baseline
    ) -> Prediction:
        rows, promoted, unpromoted = self._paths(options, context, baseline)
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
            variance = self.model.variance(rows[where], promoted[where], option[where])
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

    def _paths(
        self, options: list[PlanLine], context: PredictionContext, baseline: _Baseline
    ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        """Every store x segment week of each option's SKUs, through the pull-forward weeks,
        with the units it sells promoted and unpromoted."""
        rows, store_baseline = self._rows(options, context, baseline)
        plain = _with_ratios(
            rows.assign(price=rows["base_price"], mechanism=None, pull_forward_share=0.0)
        )
        promoted = store_baseline * np.exp(self.model.log_effect(rows))
        unpromoted = store_baseline * np.exp(self.model.log_effect(plain))
        return rows, promoted, unpromoted

    def _rows(
        self, options: list[PlanLine], context: PredictionContext, baseline: _Baseline
    ) -> tuple[pd.DataFrame, np.ndarray]:
        """Every store x segment week of each option's SKUs, through the pull-forward weeks,
        with its price terms and the store's baseline at the reference competitor index."""
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
        store_baseline = baseline.predict(
            rows[KEYS], competitor_index=rows["reference_index"].to_numpy()
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
                "units_std": np.sqrt(self.model.variance(rows, promoted, groups)),
                "baseline_units": np.bincount(groups, weights=unpromoted, minlength=size),
            }
        )

    def _competitors(self, context: PredictionContext) -> pd.DataFrame:
        competitors = self.competitors.copy()
        for (region, sku_id), price in context.competitor_prices.items():
            competitors.loc[(region.value, sku_id), "competitor_price"] = price
        return competitors


def _history_rows(
    history: DemandHistory,
    baseline: _Baseline,
    competitors: pd.DataFrame,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """Region x SKU x segment x week unit totals with their baseline offset and price terms."""
    prices = history.competitor_prices[["week_id", "region", "sku_id", "competitor_price"]]
    sales = _segment_sales(history)
    sales = _with_reference(sales, competitors[["reference_index"]])
    sales["baseline"] = baseline.predict(
        sales[KEYS], competitor_index=sales["reference_index"].to_numpy()
    )
    sales["baseline_sq"] = sales["baseline"] ** 2
    rows = sales.groupby(["week_id", *SERIES, "reference_index"], as_index=False)[
        ["units", "baseline", "baseline_sq"]
    ].sum()
    exposure = _exposure(history.promotions_history, products)
    rows = _priced(rows, exposure, SERIES, products)
    rows = _with_ratios(rows.merge(prices, on=["week_id", "region", "sku_id"]))
    rows["offset"] = np.log(rows["baseline"])
    return rows


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


def _segment_sales(history: DemandHistory) -> pd.DataFrame:
    """Units per store x SKU x segment x week, with the store's region."""
    sales = history.sales_weekly
    per_segment = pd.DataFrame(sales["segment_units"].tolist(), columns=SEGMENTS)
    per_segment[["week_id", "store_id", "sku_id"]] = sales[
        ["week_id", "store_id", "sku_id"]
    ].to_numpy()
    long = per_segment.melt(
        id_vars=["week_id", "store_id", "sku_id"], var_name="segment", value_name="units"
    )
    long = long.merge(history.stores[["store_id", "region"]], on="store_id")
    return long.astype({"week_id": int, "units": float})


def _clean_segment_sales(history: DemandHistory) -> pd.DataFrame:
    """Units per store x SKU x segment x week, keeping only weeks free of promo effects."""
    long = _segment_sales(history)
    affected = _promo_affected(history.promotions_history)
    long = long.merge(
        affected, on=["week_id", "region", "sku_id", "segment"], how="left", indicator=True
    )
    clean = long[long["_merge"] == "left_only"]
    return clean[[*KEYS, "units"]]


def _promo_affected(promotions: pd.DataFrame) -> pd.DataFrame:
    """Every (week, region, SKU, segment) a promotion or its post-promo dip touches."""
    weeks = _promo_weeks(promotions)[["week_id", *SERIES]]
    touched = pd.concat(
        [weeks.assign(week_id=weeks["week_id"] + k) for k in range(PULL_FORWARD_WEEKS + 1)]
    )
    return touched.drop_duplicates()


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


def _calendar_features(calendar: pd.DataFrame) -> pd.DataFrame:
    frame = calendar.sort_values(["region", "week_id"]).copy()
    frame["holiday_name"] = frame["holiday_name"].fillna(NO_HOLIDAY)
    frame["next_holiday_intensity"] = (
        frame.groupby("region")["holiday_intensity"].shift(-1).fillna(0.0)
    )
    angle = 2 * np.pi * pd.to_datetime(frame["week_start"]).dt.dayofyear / SEASON_DAYS
    frame["season_sin"] = np.sin(angle)
    frame["season_cos"] = np.cos(angle)
    return frame[
        [
            "week_id",
            "region",
            "holiday_name",
            "holiday_intensity",
            "next_holiday_intensity",
            "season_sin",
            "season_cos",
        ]
    ]
