"""The demand model (SPEC §9.1), stage one: a baseline forecast of units with no promotion.

A LightGBM model on the SPEC §9.1 features forecasts units per store x SKU x segment x week.
It is fitted only on clean weeks: no promotion for that SKU and segment in the week or the
four weeks before it, so neither promo uplift nor the pull-forward dip leaks into the baseline
(ADR 0023). Every fit sees only history strictly before the as-of week (ADR 0008).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

import lightgbm as lgb
import numpy as np
import pandas as pd

from promopilot.domain import Segment, TargetSegment

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
class DemandModel:
    as_of_week: int
    metrics: dict[str, float]
    _baseline: "_Baseline"

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
    return DemandModel(
        as_of_week=as_of_week,
        metrics={
            # Plan lines are region-level (ADR 0004); segment-level counts are mostly noise.
            f"baseline_wape{suffix}": _wape(holdout.groupby(grain)[["units", "predicted"]].sum())
            for suffix, grain in WAPE_GRAINS.items()
        },
        _baseline=_Baseline.fit(visible, end=as_of_week, seed=seed),
    )


def _wape(frame: pd.DataFrame) -> float:
    return float(np.abs(frame["predicted"] - frame["units"]).sum() / frame["units"].sum())


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

    def predict(self, keys: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.booster.predict(self.features.build(keys)), dtype=float)


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


def _clean_segment_sales(history: DemandHistory) -> pd.DataFrame:
    """Units per store x SKU x segment x week, keeping only weeks free of promo effects."""
    sales = history.sales_weekly
    per_segment = pd.DataFrame(sales["segment_units"].tolist(), columns=SEGMENTS)
    per_segment[["week_id", "store_id", "sku_id"]] = sales[
        ["week_id", "store_id", "sku_id"]
    ].to_numpy()
    long = per_segment.melt(
        id_vars=["week_id", "store_id", "sku_id"], var_name="segment", value_name="units"
    )
    long = long.merge(history.stores[["store_id", "region"]], on="store_id")
    affected = _promo_affected(history.promotions_history)
    long = long.merge(
        affected, on=["week_id", "region", "sku_id", "segment"], how="left", indicator=True
    )
    clean = long[long["_merge"] == "left_only"]
    return clean[[*KEYS, "units"]].astype({"week_id": int, "units": float})


def _promo_affected(promotions: pd.DataFrame) -> pd.DataFrame:
    """Every (week, region, SKU, segment) a promotion or its post-promo dip touches."""
    if promotions.empty:
        return pd.DataFrame(columns=["week_id", "region", "sku_id", "segment"])
    touched = pd.DataFrame(
        {
            "region": promotions["region"].to_numpy(),
            "week_id": [
                list(range(start, start + duration + PULL_FORWARD_WEEKS))
                for start, duration in zip(
                    promotions["start_week"], promotions["duration"], strict=True
                )
            ],
            "segment": [
                SEGMENTS if target == TargetSegment.ALL_CUSTOMERS else [target]
                for target in promotions["target_segment"]
            ],
            # A bundle cuts its partner's price too (ADR 0016).
            "sku_id": [
                [sku] if pd.isna(partner) else [sku, partner]
                for sku, partner in zip(
                    promotions["sku_id"], promotions["bundle_sku_id"], strict=True
                )
            ],
        }
    )
    touched = touched.explode("week_id").explode("segment").explode("sku_id")
    return touched.astype({"week_id": int}).drop_duplicates()


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
