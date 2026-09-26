"""The relations model (SPEC §9.2): which SKUs are substitutes and which are complements.

Cross effects: for a pair of SKUs (a, b), one pooled Poisson GLM on region x segment x week
unit totals estimates a single symmetric theta,

    log E[units_a] = log fitted_a + c_a + theta * log(p_b / p_ref_b)
    log E[units_b] = log fitted_b + c_b + theta * log(p_a / p_ref_a)

where fitted is the demand model's in-sample mean (baseline times own promo response), so
theta picks up only what the partner's price adds. Standard errors are heteroskedasticity
robust (HC0) and p-values two-sided. A theta is estimable when the partner's price moved in
those rows and the fit converged (ADR 0029).

Substitutes: every within-subcategory pair is tested, and a pair is kept when its
Benjamini-Hochberg q over all tested pairs is below 0.05 and theta is at least the minimum
effect size (ADR 0013).

Complements: basket lift P(a and b) / (P(a) P(b)) above 1.5 with a minimum support (the
share of baskets holding both). Where theta is estimable, a candidate is confirmed only by
theta < 0 with BH q < 0.05 over the estimable candidates; otherwise lift alone decides.

Every fit sees only sales, promotions and baskets strictly before the as-of week (ADR 0008).

Effect calculators (ADR 0033): a plan line's price cut moves every detected substitute and
complement B in its region, in scope or not (ADR 0005), over its promo weeks and targeted
segments, by B's baseline x (exp(sum of theta x log(p_eff / base)) - 1), at B's base margin.
A fall in profit is cannibalisation and a rise is halo, as the oracle counts them (ADR 0017).
`pairwise_cannibalisation` corrects the single-line figures for two lines promoted together.
"""

import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from promopilot.domain import PlanLine, Segment, TargetSegment
from promopilot.economics import effective_unit_price
from promopilot.models.demand import DemandHistory, DemandModel, PredictionContext

CELL = ["week_id", "region", "segment"]
"""The unit a cross effect is fitted on: our prices are set per region and segment."""


@dataclass(frozen=True)
class RelationsConfig:
    """Detection thresholds, recorded with each relations version in the registry."""

    substitute_max_q: float = 0.05
    substitute_min_theta: float = 0.1
    """The minimum cross-price effect size of a substitute (ADR 0013)."""
    complement_min_lift: float = 1.5
    complement_min_support: float = 0.001
    """The minimum share of baskets that hold both SKUs."""
    complement_max_q: float = 0.05


@dataclass(frozen=True)
class CrossPriceEffect:
    """theta: the effect of one SKU's log price ratio on the other's log units (symmetric)."""

    theta: float
    std_error: float
    p_value: float
    """Two-sided, from the robust standard error; before any multiple-testing adjustment."""


PAIR_KEYS = ["sku_a", "sku_b"]
"""A pair is stored once, with sku_a < sku_b."""


@dataclass(frozen=True)
class Relations:
    as_of_week: int
    config: RelationsConfig
    metrics: dict[str, float]
    _pairs: pd.DataFrame = field(repr=False)
    """Indexed by PAIR_KEYS: theta, std_error, p_value (NaN where not estimated), lift,
    support (NaN where not a complement candidate), q_value, substitute, complement."""

    def substitutes(self, sku_id: str) -> pd.DataFrame:
        """sku_id, theta, std_error, q_value of each substitute, the strongest first."""
        partners = self._partners(sku_id, "substitute")
        partners = partners.sort_values(["theta", "sku_id"], ascending=[False, True])
        return partners[["sku_id", "theta", "std_error", "q_value"]].reset_index(drop=True)

    def complements(self, sku_id: str) -> pd.DataFrame:
        """sku_id, lift, support, theta, std_error of each complement, the highest lift first.

        theta and std_error are NaN where the cross effect is not estimable.
        """
        partners = self._partners(sku_id, "complement")
        partners = partners.sort_values(["lift", "sku_id"], ascending=[False, True])
        return partners[["sku_id", "lift", "support", "theta", "std_error"]].reset_index(drop=True)

    def cross_effect(self, sku_id: str, other_sku_id: str) -> CrossPriceEffect | None:
        """The estimated cross effect of a pair, or None if the fit did not estimate it."""
        key = (min(sku_id, other_sku_id), max(sku_id, other_sku_id))
        if sku_id == other_sku_id or key not in self._pairs.index:
            return None
        effects = self._pairs[["theta", "std_error", "p_value"]]
        theta, std_error, p_value = effects.loc[[key]].to_numpy(dtype=float)[0]
        if np.isnan(theta):
            return None
        return CrossPriceEffect(
            theta=float(theta), std_error=float(std_error), p_value=float(p_value)
        )

    def _partners(self, sku_id: str, kind: str) -> pd.DataFrame:
        pairs = self._pairs[self._pairs[kind]].reset_index()
        as_a = pairs[pairs["sku_a"] == sku_id].assign(sku_id=lambda frame: frame["sku_b"])
        as_b = pairs[pairs["sku_b"] == sku_id].assign(sku_id=lambda frame: frame["sku_a"])
        q_value = f"{kind}_q"
        return pd.concat([as_a, as_b]).rename(columns={q_value: "q_value"})


def fit(
    history: DemandHistory,
    baskets: pd.DataFrame,
    demand_model: DemandModel,
    as_of_week: int,
    seed: int,
    config: RelationsConfig | None = None,
) -> Relations:
    """Detect substitutes and complements from the history and baskets before `as_of_week`.

    The fit draws no random numbers, so `seed` changes nothing; it is taken so every model
    fit has the same shape (CLAUDE.md), and the result is identical for identical inputs.
    """
    del seed
    config = config or RelationsConfig()
    if demand_model.as_of_week != as_of_week:
        raise ValueError(
            f"the demand model was fitted as of week {demand_model.as_of_week}, "
            f"not the as-of week {as_of_week}"
        )
    visible = history.before(as_of_week)
    baskets = baskets[baskets["week_id"] < as_of_week]
    panel = _Panel.of(demand_model.fitted_history(visible))

    tested = _cross_effects(panel, _within_subcategory_pairs(visible.products))
    tested["substitute_q"] = _bh(tested["p_value"])
    tested["substitute"] = (tested["substitute_q"] < config.substitute_max_q) & (
        tested["theta"] >= config.substitute_min_theta
    )

    lift = _basket_lift(baskets)
    candidates = lift[
        (lift["lift"] > config.complement_min_lift)
        & (lift["support"] >= config.complement_min_support)
    ]
    untested = candidates.index.difference(tested.index)
    effects = pd.concat([tested, _cross_effects(panel, list(untested))])
    candidates = candidates.join(effects[["theta", "std_error", "p_value"]])
    estimable = candidates["theta"].notna()
    candidates["complement_q"] = np.nan
    candidates.loc[estimable, "complement_q"] = _bh(candidates.loc[estimable, "p_value"])
    candidates["complement"] = ~estimable | (
        (candidates["complement_q"] < config.complement_max_q) & (candidates["theta"] < 0)
    )

    pairs = effects[["theta", "std_error", "p_value", "substitute_q", "substitute"]].join(
        candidates[["lift", "support", "complement_q", "complement"]], how="outer"
    )
    pairs = pairs.fillna({"substitute": False, "complement": False}).astype(
        {"substitute": bool, "complement": bool}
    )
    return Relations(
        as_of_week=as_of_week,
        config=config,
        metrics={
            "substitute_pairs": float(pairs["substitute"].sum()),
            "substitute_pairs_tested": float(len(tested)),
            "complement_pairs": float(pairs["complement"].sum()),
            "complement_candidates": float(len(candidates)),
            "complement_candidates_estimable": float(estimable.sum()),
            "baskets": float(len(baskets)),
            "substitute_max_q": config.substitute_max_q,
            "substitute_min_theta": config.substitute_min_theta,
            "complement_min_lift": config.complement_min_lift,
            "complement_min_support": config.complement_min_support,
            "complement_max_q": config.complement_max_q,
        },
        _pairs=pairs.sort_index(),
    )


@dataclass(frozen=True)
class _Panel:
    """The demand model's fit as cell x SKU matrices: units, log fitted mean, log price ratio."""

    sku_index: dict[str, int]
    units: np.ndarray
    log_fitted: np.ndarray
    log_price_ratio: np.ndarray

    @classmethod
    def of(cls, fitted: pd.DataFrame) -> "_Panel":
        wide = fitted.pivot(
            index=CELL, columns="sku_id", values=["units", "fitted_units", "log_price_ratio"]
        )
        sku_ids = sorted(fitted["sku_id"].unique())

        def matrix(value: str) -> np.ndarray:
            return np.asarray(pd.DataFrame(wide[value]).reindex(columns=sku_ids), dtype=float)

        # A SKU missing from a cell has no row to fit (NaN); a partner missing paid base price.
        return cls(
            sku_index={sku_id: k for k, sku_id in enumerate(sku_ids)},
            units=matrix("units"),
            log_fitted=np.log(matrix("fitted_units")),
            log_price_ratio=np.nan_to_num(matrix("log_price_ratio"), nan=0.0),
        )

    def cross_effect(self, sku_a: str, sku_b: str) -> CrossPriceEffect | None:
        """The pooled symmetric theta of a pair, or None when it is not estimable."""
        if sku_a not in self.sku_index or sku_b not in self.sku_index:
            return None
        a, b = self.sku_index[sku_a], self.sku_index[sku_b]
        units = np.concatenate([self.units[:, a], self.units[:, b]])
        offset = np.concatenate([self.log_fitted[:, a], self.log_fitted[:, b]])
        partner = np.concatenate([self.log_price_ratio[:, b], self.log_price_ratio[:, a]])
        own = np.concatenate([np.ones(len(self.units)), np.zeros(len(self.units))])
        usable = np.isfinite(units) & np.isfinite(offset)
        if not (partner[usable] != 0).any():
            return None
        design = np.column_stack([own, 1 - own, partner])[usable]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = sm.GLM(
                    units[usable], design, family=sm.families.Poisson(), offset=offset[usable]
                ).fit(cov_type="HC0")
        except (ValueError, np.linalg.LinAlgError):
            return None
        theta, std_error, p_value = result.params[2], result.bse[2], result.pvalues[2]
        converged = bool(getattr(result, "converged", True))
        if not (converged and np.isfinite([theta, std_error, p_value]).all() and std_error > 0):
            return None
        return CrossPriceEffect(
            theta=float(theta), std_error=float(std_error), p_value=float(p_value)
        )


def _cross_effects(panel: _Panel, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """theta, std_error, p_value for each estimable pair, indexed by PAIR_KEYS."""
    rows = []
    for sku_a, sku_b in pairs:
        effect = panel.cross_effect(sku_a, sku_b)
        if effect is not None:
            rows.append((sku_a, sku_b, effect.theta, effect.std_error, effect.p_value))
    frame = pd.DataFrame(rows, columns=[*PAIR_KEYS, "theta", "std_error", "p_value"])
    return frame.set_index(PAIR_KEYS)


def _within_subcategory_pairs(products: pd.DataFrame) -> list[tuple[str, str]]:
    ordered = products.sort_values("sku_id")
    return [
        (sku_a, sku_b)
        for _, group in ordered.groupby("subcategory", sort=True)
        for sku_a, sku_b in combinations(group["sku_id"], 2)
    ]


def _basket_lift(baskets: pd.DataFrame) -> pd.DataFrame:
    """together, support and lift of every pair seen in a basket, indexed by PAIR_KEYS."""
    empty = pd.DataFrame(
        columns=["together", "support", "lift"],
        index=pd.MultiIndex.from_tuples([], names=PAIR_KEYS),
        dtype=float,
    )
    count = len(baskets)
    if count == 0:
        return empty
    items = pd.DataFrame(
        {"basket": np.arange(count), "sku_id": baskets["sku_ids"].to_numpy()}
    ).explode("sku_id")
    items = items.dropna().drop_duplicates()
    share = items.groupby("sku_id").size() / count
    both = items.merge(items, on="basket", suffixes=("_a", "_b"))
    both = both[both["sku_id_a"] < both["sku_id_b"]]
    if both.empty:
        return empty
    together = both.groupby(["sku_id_a", "sku_id_b"]).size().rename("together")
    together.index = together.index.set_names(PAIR_KEYS)
    frame = together.astype(float).to_frame()
    frame["support"] = frame["together"] / count
    sku_a = frame.index.get_level_values("sku_a")
    sku_b = frame.index.get_level_values("sku_b")
    expected = share.reindex(sku_a).to_numpy() * share.reindex(sku_b).to_numpy()
    frame["lift"] = frame["support"] / expected
    return frame


def _bh(p_values: pd.Series) -> np.ndarray:
    """Benjamini-Hochberg q-values."""
    if p_values.empty:
        return np.array([], dtype=float)
    return np.asarray(multipletests(p_values.to_numpy(dtype=float), method="fdr_bh")[1])


# --- effect calculators (ADR 0033) ------------------------------------------------------


class RelationLookup(Protocol):
    """The detected relations of a SKU (`Relations`)."""

    def substitutes(self, sku_id: str) -> pd.DataFrame: ...

    def complements(self, sku_id: str) -> pd.DataFrame: ...


class BaselineForecast(Protocol):
    """No-promotion units per week, store, SKU and segment (`DemandModel.baseline`)."""

    def baseline(
        self,
        weeks: Iterable[int],
        *,
        regions: Sequence[str] | None = None,
        store_ids: Sequence[str] | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame: ...


class LineForecast(BaselineForecast, Protocol):
    """Also a line's own SKUs per week and segment (`DemandModel.line_paths`)."""

    def line_paths(
        self, options: Sequence[PlanLine], context: PredictionContext
    ) -> pd.DataFrame: ...


EFFECT_COLUMNS = [
    "line",
    "region",
    "sku_id",
    "relation",
    "baseline_units",
    "units_change",
    "units_change_pct",
    "profit_change",
    "cannibalised_profit",
    "halo_profit",
]
"""One row per plan line and SKU it moves (`line_effects`)."""


def line_effects(
    lines: Sequence[PlanLine],
    relations: RelationLookup,
    demand_model: BaselineForecast,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """The cannibalisation and halo of each plan line, as if it ran alone (ADR 0033).

    One row (EFFECT_COLUMNS) per line and each detected substitute or complement with an
    estimated theta of the line's SKUs, other than those SKUs, in the line's region, the
    largest profit change first:

    - baseline_units: that SKU's no-promotion units over the promo weeks, every segment;
    - units_change: baseline units of the targeted segments x (exp(c) - 1), where c sums
      theta x log(effective price / base price) over the line's SKUs;
    - units_change_pct: units_change as a percentage of baseline_units;
    - profit_change: units_change x (base price - unit cost), in rupees;
    - cannibalised_profit is the profit lost (a fall) and halo_profit the profit gained.

    Other SKUs are assumed at base price, and the units are not stock-capped (ADR 0017).
    `products` needs sku_id, base_price and unit_cost.
    """
    economics = _Economics.of(products)
    frames = []
    for n, line in enumerate(lines):
        shifts = _price_shifts(line, relations, economics)
        if not shifts:
            continue
        affected = sorted(shifts)
        baseline = demand_model.baseline(
            _weeks(line), regions=[line.region.value], sku_ids=affected
        )
        targeted = baseline[baseline["segment"].isin(_segments(line))]
        base = _units_by_sku(baseline, affected)
        units_change = _units_by_sku(targeted, affected) * np.expm1(
            [shifts[sku_id][1] for sku_id in affected]
        )
        profit_change = units_change * economics.margins(affected)
        frames.append(
            pd.DataFrame(
                {
                    "line": n,
                    "region": line.region.value,
                    "sku_id": affected,
                    "relation": [shifts[sku_id][0] for sku_id in affected],
                    "baseline_units": base,
                    "units_change": units_change,
                    "units_change_pct": np.divide(
                        100 * units_change, base, out=np.zeros_like(base), where=base > 0
                    ),
                    "profit_change": profit_change,
                    "cannibalised_profit": np.maximum(-profit_change, 0.0),
                    "halo_profit": np.maximum(profit_change, 0.0),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=EFFECT_COLUMNS)
    effects = pd.concat(frames, ignore_index=True)
    effects = effects.assign(size=effects["profit_change"].abs())
    effects = effects.sort_values(["line", "size", "sku_id"], ascending=[True, False, True])
    return effects[EFFECT_COLUMNS].reset_index(drop=True)


def pairwise_cannibalisation(
    line: PlanLine,
    other: PlanLine,
    relations: RelationLookup,
    demand_model: LineForecast,
    products: pd.DataFrame,
    context: PredictionContext | None = None,
) -> float:
    """What promoting two substitute lines together loses beyond their single-line figures.

    The optimiser subtracts it once for each such pair it selects (SPEC §9.4 y_ij, ADR 0033).
    It is the two lines' single-line figures (own incremental profit plus `line_effects`)
    minus their joint effect, over the weeks and segments both lines price:

    - each line's own SKUs lose (exp(c) - 1) of their promoted units at their promoted
      margin, where the other line's single-line figure charged baseline units at base
      margin;
    - a SKU both lines move is moved by both at once, not by each separately.

    It is 0 for lines in different regions, with no week or segment in common, or where no
    SKU of one is a detected substitute of a SKU of the other. It can be negative: a deep
    promotion that sells at a loss loses less to its substitute's cut.
    """
    if line.region is not other.region:
        return 0.0
    if not any(
        partner in set(relations.substitutes(sku_id)["sku_id"])
        for sku_id in line.skus
        for partner in other.skus
    ):
        return 0.0
    weeks = sorted(set(_weeks(line)) & set(_weeks(other)))
    segments = sorted(set(_segments(line)) & set(_segments(other)))
    if not weeks or not segments:
        return 0.0
    economics = _Economics.of(products)
    shifts = (_price_shifts(line, relations, economics), _price_shifts(other, relations, economics))

    paths = demand_model.line_paths([line, other], context or PredictionContext())
    paths = paths[paths["week_id"].isin(weeks) & paths["segment"].isin(segments)]
    interaction = 0.0
    for n, (own, moved_by) in enumerate(((line, shifts[1]), (other, shifts[0]))):
        for sku_id in own.skus:
            if sku_id not in moved_by:
                continue
            rows = paths[(paths["option"] == n) & (paths["sku_id"] == sku_id)]
            base_price = economics.base_price[sku_id]
            unit_cost = economics.unit_cost[sku_id]
            promoted = float((rows["units"] * (rows["price"] - unit_cost)).sum())
            unpromoted = float(rows["baseline_units"].sum()) * (base_price - unit_cost)
            interaction += float(np.expm1(moved_by[sku_id][1])) * (promoted - unpromoted)

    both = sorted((set(shifts[0]) & set(shifts[1])) - set(line.skus) - set(other.skus))
    if both:
        baseline = demand_model.baseline(weeks, regions=[line.region.value], sku_ids=both)
        units = _units_by_sku(baseline[baseline["segment"].isin(segments)], both)
        first = np.expm1([shifts[0][sku_id][1] for sku_id in both])
        second = np.expm1([shifts[1][sku_id][1] for sku_id in both])
        interaction += float((units * first * second * economics.margins(both)).sum())
    return -interaction


def _price_shifts(
    line: PlanLine, relations: RelationLookup, economics: "_Economics"
) -> dict[str, tuple[str, float]]:
    """The relation and c = sum of theta x log(p_eff / base) of each SKU the line moves."""
    shifts: dict[str, tuple[str, float]] = {}
    for sku_id in line.skus:
        base_price = economics.base_price[sku_id]
        effective = effective_unit_price(line.mechanism, base_price, line.depth_pct)
        log_ratio = float(np.log(effective / base_price))
        for relation, partners in (
            ("substitute", relations.substitutes(sku_id)),
            ("complement", relations.complements(sku_id)),
        ):
            for partner, theta in zip(partners["sku_id"], partners["theta"], strict=True):
                if partner in line.skus or not np.isfinite(theta):
                    continue
                known, change = shifts.get(str(partner), (relation, 0.0))
                shifts[str(partner)] = (known, change + float(theta) * log_ratio)
    return shifts


def _units_by_sku(baseline: pd.DataFrame, sku_ids: list[str]) -> np.ndarray:
    units = baseline.groupby("sku_id")["units"].sum().reindex(sku_ids, fill_value=0.0)
    return np.asarray(units, dtype=float)


@dataclass(frozen=True)
class _Economics:
    """Base price and unit cost per SKU, in rupees."""

    base_price: dict[str, float]
    unit_cost: dict[str, float]

    @classmethod
    def of(cls, products: pd.DataFrame) -> "_Economics":
        sku_ids = [str(sku_id) for sku_id in products["sku_id"]]
        return cls(
            base_price=dict(zip(sku_ids, map(float, products["base_price"]), strict=True)),
            unit_cost=dict(zip(sku_ids, map(float, products["unit_cost"]), strict=True)),
        )

    def margins(self, sku_ids: list[str]) -> np.ndarray:
        """Base price minus unit cost of each SKU."""
        return np.array([self.base_price[sku] - self.unit_cost[sku] for sku in sku_ids])


def _weeks(line: PlanLine) -> list[int]:
    return list(range(line.start_week, line.start_week + line.duration_weeks))


def _segments(line: PlanLine) -> list[str]:
    if line.target_segment is TargetSegment.ALL_CUSTOMERS:
        return [segment.value for segment in Segment]
    return [line.target_segment.value]
