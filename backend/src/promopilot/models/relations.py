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
from functools import cached_property
from itertools import combinations
from typing import Protocol

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from promopilot.domain import Mechanism, PlanLine, Region, Segment, TargetSegment
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
        partners, none = self._partner_index[kind]
        return partners.get(sku_id, none)

    @cached_property
    def _partner_index(self) -> dict[str, tuple[dict[str, pd.DataFrame], pd.DataFrame]]:
        """Per kind, each SKU's pairs of that kind with the partner as sku_id, and the empty
        table: built on the first lookup, so a lookup no longer scans every pair (ADR 0077)."""
        index = {}
        for kind in ("substitute", "complement"):
            pairs = self._pairs[self._pairs[kind]].reset_index()
            as_a = pairs.assign(sku_id=pairs["sku_b"], _of=pairs["sku_a"])
            as_b = pairs.assign(sku_id=pairs["sku_a"], _of=pairs["sku_b"])
            both = pd.concat([as_a, as_b]).rename(columns={f"{kind}_q": "q_value"})
            index[kind] = (
                {
                    str(of): partners.drop(columns="_of")
                    for of, partners in both.groupby("_of", sort=False)
                },
                both.iloc[0:0].drop(columns="_of"),
            )
        return index

    def __getstate__(self) -> dict[str, object]:
        # The registry pickles the model (ADR 0023): the index is rebuilt, never stored.
        state = dict(self.__dict__)
        state.pop("_partner_index", None)
        return state


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

    The baseline is forecast once per region, for every week and SKU the region's lines
    need, and each line reads its own rows off it in the order a forecast of its weeks and
    SKUs alone lists them, so every number is exactly the one-line figure (ADR 0077).
    """
    economics = _Economics.of(products)
    lookup = _MemoLookup(relations)
    moving = [
        (n, line, shifts)
        for n, line in enumerate(lines)
        if (shifts := _price_shifts(line, lookup, economics))
    ]
    forecasts = _regional_baselines(
        demand_model, [(line, sorted(shifts)) for _, line, shifts in moving]
    )
    frames = []
    for n, line, shifts in moving:
        affected = sorted(shifts)
        forecast = forecasts[line.region.value]
        baseline = forecast[
            forecast["week_id"].isin(_weeks(line)) & forecast["sku_id"].isin(affected)
        ]
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


def _regional_baselines(
    demand_model: BaselineForecast, lines: Sequence[tuple[PlanLine, list[str]]]
) -> dict[str, pd.DataFrame]:
    """One baseline forecast per region: every week any of its lines runs, and every SKU any
    of them moves (each line with the SKUs it moves)."""
    weeks: dict[str, set[int]] = {}
    skus: dict[str, set[str]] = {}
    for line, affected in lines:
        region = line.region.value
        weeks.setdefault(region, set()).update(_weeks(line))
        skus.setdefault(region, set()).update(affected)
    return {
        region: demand_model.baseline(
            sorted(weeks[region]), regions=[region], sku_ids=sorted(skus[region])
        )
        for region in weeks
    }


def line_effect_totals(
    lines: Sequence[PlanLine],
    relations: RelationLookup,
    demand_model: BaselineForecast,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """Each line's `line_effects` summed: cannibalised_profit and halo_profit, in input order.

    The same numbers as totalling `line_effects` per line, computed for a whole batch at once
    (promo option generation prices tens of thousands of lines, ADR 0035): the baseline is
    forecast once per region, and lines that cut the same SKUs to the same prices share
    their price shifts. A line that moves nothing has zeros.
    """
    economics = _Economics.of(products)
    lookup = _MemoLookup(relations)
    shifts_of: dict[tuple[tuple[str, ...], Mechanism, int], dict[str, tuple[str, float]]] = {}
    moved: dict[str, list[object]] = {key: [] for key in ("line", "sku", "change")}
    spans: list[tuple[str, int, int, int]] = []
    for n, line in enumerate(lines):
        key = (line.skus, line.mechanism, line.depth_pct)
        if key not in shifts_of:
            shifts_of[key] = _price_shifts(line, lookup, economics)
        for sku_id, (_, change) in shifts_of[key].items():
            moved["line"].append(n)
            moved["sku"].append(sku_id)
            moved["change"].append(change)
        spans.append((line.region.value, line.start_week, line.duration_weeks, _segment(line)))

    cannibalised = np.zeros(len(lines))
    halo = np.zeros(len(lines))
    if moved["line"]:
        rows = pd.DataFrame(moved)
        span = pd.DataFrame(spans, columns=["region", "start", "duration", "segment"])
        rows = rows.join(span, on="line")
        affected = sorted(set(rows["sku"]))
        column = {sku_id: k for k, sku_id in enumerate(affected)}
        sku = rows["sku"].map(column).to_numpy()
        units = np.zeros(len(rows))
        starts = rows["start"].to_numpy(dtype=int)
        ends = starts + rows["duration"].to_numpy(dtype=int)
        segments = rows["segment"].to_numpy(dtype=int)
        for region, at in rows.groupby("region").indices.items():
            first = int(starts[at].min())
            cumulative = _cumulative_baseline(
                demand_model, str(region), range(first, int(ends[at].max())), affected
            )
            window = cumulative[ends[at] - first, sku[at]] - cumulative[starts[at] - first, sku[at]]
            everyone = segments[at] == len(SEGMENT_NAMES)
            one = np.minimum(segments[at], len(SEGMENT_NAMES) - 1)
            units[at] = np.where(everyone, window.sum(axis=1), window[np.arange(len(at)), one])
        units_change = units * np.expm1(rows["change"].to_numpy(dtype=float))
        profit = units_change * economics.margins(affected)[sku]
        line_of = rows["line"].to_numpy(dtype=int)
        cannibalised = np.bincount(line_of, np.maximum(-profit, 0.0), minlength=len(lines))
        halo = np.bincount(line_of, np.maximum(profit, 0.0), minlength=len(lines))
    return pd.DataFrame({"cannibalised_profit": cannibalised, "halo_profit": halo})


SEGMENT_NAMES = [segment.value for segment in Segment]


class _MemoLookup:
    """A relation lookup that asks for each SKU's partners once."""

    def __init__(self, relations: RelationLookup) -> None:
        self._relations = relations
        self._substitutes: dict[str, pd.DataFrame] = {}
        self._complements: dict[str, pd.DataFrame] = {}

    def substitutes(self, sku_id: str) -> pd.DataFrame:
        if sku_id not in self._substitutes:
            self._substitutes[sku_id] = self._relations.substitutes(sku_id)
        return self._substitutes[sku_id]

    def complements(self, sku_id: str) -> pd.DataFrame:
        if sku_id not in self._complements:
            self._complements[sku_id] = self._relations.complements(sku_id)
        return self._complements[sku_id]


def _segment(line: PlanLine) -> int:
    """The targeted segment's position in SEGMENT_NAMES, or its length for All customers."""
    if line.target_segment is TargetSegment.ALL_CUSTOMERS:
        return len(SEGMENT_NAMES)
    return SEGMENT_NAMES.index(line.target_segment.value)


def _cumulative_baseline(
    demand_model: BaselineForecast, region: str, weeks: range, sku_ids: list[str]
) -> np.ndarray:
    """Baseline units summed over the region's stores, cumulated over the weeks.

    Indexed [weeks elapsed, SKU, segment]: row k holds the first k weeks' total, so a span's
    units are one subtraction.
    """
    baseline = demand_model.baseline(list(weeks), regions=[region], sku_ids=sku_ids)
    grid = (
        baseline.groupby(["week_id", "sku_id", "segment"])["units"]
        .sum()
        .reindex(pd.MultiIndex.from_product([list(weeks), sku_ids, SEGMENT_NAMES]), fill_value=0.0)
        .to_numpy(dtype=float)
        .reshape(len(weeks), len(sku_ids), len(SEGMENT_NAMES))
    )
    return np.concatenate([np.zeros((1, *grid.shape[1:])), np.cumsum(grid, axis=0)])


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

    This is the definition, one pair at a time; `pairwise_cannibalisations` computes the same
    terms for a whole batch at once.
    """
    if line.region is not other.region or not _substitutes(line, other, relations):
        return 0.0
    weeks = sorted(set(_weeks(line)) & set(_weeks(other)))
    segments = sorted(set(_segments(line)) & set(_segments(other)))
    if not weeks or not segments:
        return 0.0
    economics = _Economics.of(products)
    moves = _price_shifts(line, relations, economics)
    other_moves = _price_shifts(other, relations, economics)
    paths = demand_model.line_paths([line, other], context or PredictionContext())
    paths = paths[paths["week_id"].isin(weeks) & paths["segment"].isin(segments)]

    interaction = 0.0
    for option, (own_line, moved_by) in enumerate(((line, other_moves), (other, moves))):
        for sku_id in own_line.skus:
            if sku_id not in moved_by:
                continue
            rows = paths[(paths["option"] == option) & (paths["sku_id"] == sku_id)]
            unit_cost = economics.unit_cost[sku_id]
            promoted = float((rows["units"] * (rows["price"] - unit_cost)).sum())
            unpromoted = float(rows["baseline_units"].sum()) * (
                economics.base_price[sku_id] - unit_cost
            )
            interaction += float(np.expm1(moved_by[sku_id][1])) * (promoted - unpromoted)
    both = sorted(set(moves) & set(other_moves) - set(line.skus) - set(other.skus))
    if both:
        baseline = demand_model.baseline(weeks, regions=[line.region.value], sku_ids=both)
        units = _units_by_sku(baseline[baseline["segment"].isin(segments)], both)
        first = np.expm1([moves[sku_id][1] for sku_id in both])
        second = np.expm1([other_moves[sku_id][1] for sku_id in both])
        interaction += float((units * first * second * economics.margins(both)).sum())
    return -interaction


def pairwise_cannibalisations(
    pairs: Sequence[tuple[PlanLine, PlanLine]],
    relations: RelationLookup,
    demand_model: LineForecast,
    products: pd.DataFrame,
    context: PredictionContext | None = None,
) -> np.ndarray:
    """`pairwise_cannibalisation` of every pair, in input order, computed as one batch.

    The optimiser prices every pair of promo options it could select together (ADR 0036), a
    few hundred thousand on the demo brief, so the batch is vectorised across pairs (#112):

    - which pairs have a term at all (same region, a common week and segment, a substitute
      between them) is decided on arrays, per distinct line and per distinct set of SKUs;
    - the lines' own units come from one `line_paths` call, and the baseline is forecast
      once per region, both cumulated over the weeks so a pair's overlap is one subtraction;
    - each SKU's relations, and the price shifts of lines that cut the same SKUs to the
      same prices, are looked up once.

    Lines are told apart by identity: an equal line passed as two objects is priced twice.
    """
    result = np.zeros(len(pairs))
    lookup = _MemoLookup(relations)
    lines, first, second = _distinct_lines(pairs)
    spans = _Spans.of(lines)
    live = np.flatnonzero(
        spans.overlap(first, second) & _substitute_pairs(lines, first, second, lookup)
    )
    if live.size == 0:
        return result
    first, second = first[live], second[live]
    start = np.maximum(spans.start[first], spans.start[second])
    end = np.minimum(spans.end[first], spans.end[second])
    everyone = spans.segment[first] == len(SEGMENT_NAMES)
    segment = np.where(everyone, spans.segment[second], spans.segment[first])

    economics = _Economics.of(products)
    predicted = np.unique(np.concatenate([first, second]))
    moves = dict(
        zip(
            predicted.tolist(),
            _line_shifts([lines[k] for k in predicted], lookup, economics),
            strict=True,
        )
    )
    own = _Terms()
    shared = _Terms()
    for n, (a, b) in enumerate(zip(first.tolist(), second.tolist(), strict=True)):
        moved_a, moved_b = moves[a], moves[b]
        for own_line, moved_by in ((a, moved_b), (b, moved_a)):
            for sku_id in lines[own_line].skus:
                if sku_id in moved_by:
                    own.add(n, own_line, sku_id, np.expm1(moved_by[sku_id][1]))
        for sku_id in moved_a.keys() & moved_b.keys():
            if sku_id not in lines[a].skus and sku_id not in lines[b].skus:
                both = np.expm1(moved_a[sku_id][1]) * np.expm1(moved_b[sku_id][1])
                shared.add(n, a, sku_id, both * economics.margin(sku_id))

    interaction = np.zeros(live.size)
    if own.pair:
        # A line's own SKU: (exp(c) - 1) x (promoted profit - its baseline profit at base).
        paths = demand_model.line_paths(
            [lines[k] for k in predicted], context or PredictionContext()
        )
        pair = np.asarray(own.pair, dtype=np.intp)
        first_week = int(start.min())
        cumulative, cell = _own_profit_change(
            paths,
            np.searchsorted(predicted, np.asarray(own.line, dtype=np.intp)),
            own.sku,
            range(first_week, int(end.max())),
            economics,
        )
        window = (
            cumulative[end[pair] - first_week, cell] - cumulative[start[pair] - first_week, cell]
        )
        interaction += np.bincount(
            pair, np.asarray(own.weight) * _in_segment(window, segment[pair]), minlength=live.size
        )
    if shared.pair:
        # A SKU both lines move: the two cuts' overlap on its baseline units, at base margin.
        pair = np.asarray(shared.pair, dtype=np.intp)
        region = spans.region[np.asarray(shared.line, dtype=np.intp)]
        units = np.zeros(pair.size)
        for code in np.unique(region).tolist():
            at = np.flatnonzero(region == code)
            affected = sorted({shared.sku[k] for k in at})
            column = {sku_id: k for k, sku_id in enumerate(affected)}
            sku = np.array([column[shared.sku[k]] for k in at], dtype=np.intp)
            first_week = int(start[pair[at]].min())
            cumulative = _cumulative_baseline(
                demand_model,
                REGIONS[code].value,
                range(first_week, int(end[pair[at]].max())),
                affected,
            )
            window = (
                cumulative[end[pair[at]] - first_week, sku]
                - cumulative[start[pair[at]] - first_week, sku]
            )
            units[at] = _in_segment(window, segment[pair[at]])
        interaction += np.bincount(pair, units * np.asarray(shared.weight), minlength=live.size)
    result[live] = -interaction
    return result


REGIONS = list(Region)


class _Terms:
    """Rows of a batch's pairwise terms: the pair, a line, a SKU and its weight."""

    def __init__(self) -> None:
        self.pair: list[int] = []
        self.line: list[int] = []
        self.sku: list[str] = []
        self.weight: list[float] = []

    def add(self, pair: int, line: int, sku_id: str, weight: float) -> None:
        self.pair.append(pair)
        self.line.append(line)
        self.sku.append(sku_id)
        self.weight.append(float(weight))


def _distinct_lines(
    pairs: Sequence[tuple[PlanLine, PlanLine]],
) -> tuple[list[PlanLine], np.ndarray, np.ndarray]:
    """The distinct lines, by identity, and each pair's first and second line among them."""
    index: dict[int, int] = {}
    lines: list[PlanLine] = []
    ends = np.empty(2 * len(pairs), dtype=np.intp)
    n = 0
    for pair in pairs:
        for line in pair:
            k = index.get(id(line))
            if k is None:
                k = index[id(line)] = len(lines)
                lines.append(line)
            ends[n] = k
            n += 1
    return lines, ends[0::2], ends[1::2]


@dataclass(frozen=True)
class _Spans:
    """Each line's region, promo weeks [start, end) and segment (`_segment`), as arrays."""

    region: np.ndarray
    start: np.ndarray
    end: np.ndarray
    segment: np.ndarray

    @classmethod
    def of(cls, lines: Sequence[PlanLine]) -> "_Spans":
        regions = {region: k for k, region in enumerate(REGIONS)}
        return cls(
            region=np.array([regions[line.region] for line in lines], dtype=np.intp),
            start=np.array([line.start_week for line in lines], dtype=np.intp),
            end=np.array([line.start_week + line.duration_weeks for line in lines], dtype=np.intp),
            segment=np.array([_segment(line) for line in lines], dtype=np.intp),
        )

    def overlap(self, first: np.ndarray, second: np.ndarray) -> np.ndarray:
        """Whether each pair of lines shares its region, a promo week and a segment."""
        everyone = len(SEGMENT_NAMES)
        a, b = self.segment[first], self.segment[second]
        weeks = np.maximum(self.start[first], self.start[second]) < np.minimum(
            self.end[first], self.end[second]
        )
        same_region = self.region[first] == self.region[second]
        return np.asarray(same_region & weeks & ((a == everyone) | (b == everyone) | (a == b)))


def _substitute_pairs(
    lines: Sequence[PlanLine], first: np.ndarray, second: np.ndarray, relations: RelationLookup
) -> np.ndarray:
    """`_substitutes` of each pair of lines, decided once per pair of distinct SKU sets."""
    groups: dict[tuple[str, ...], int] = {}
    group = np.array([groups.setdefault(line.skus, len(groups)) for line in lines], dtype=np.intp)
    partners = [
        {str(partner) for sku_id in skus for partner in relations.substitutes(sku_id)["sku_id"]}
        for skus in groups
    ]
    matrix = np.array(
        [[any(sku_id in found for sku_id in skus) for skus in groups] for found in partners],
        dtype=bool,
    ).reshape(len(groups), len(groups))
    return np.asarray(matrix[group[first], group[second]], dtype=bool)


def _line_shifts(
    lines: Sequence[PlanLine], relations: RelationLookup, economics: "_Economics"
) -> list[dict[str, tuple[str, float]]]:
    """`_price_shifts` of each line, worked out once per SKU set, mechanism and depth."""
    known: dict[tuple[tuple[str, ...], Mechanism, int], dict[str, tuple[str, float]]] = {}
    shifts = []
    for line in lines:
        key = (line.skus, line.mechanism, line.depth_pct)
        if key not in known:
            known[key] = _price_shifts(line, relations, economics)
        shifts.append(known[key])
    return shifts


def _own_profit_change(
    paths: pd.DataFrame,
    options: np.ndarray,
    sku_ids: Sequence[str],
    weeks: range,
    economics: "_Economics",
) -> tuple[np.ndarray, np.ndarray]:
    """Promoted profit minus baseline profit at base price, of options' own SKUs.

    `paths` are `line_paths` rows. Returns that change cumulated over the weeks, indexed
    [weeks elapsed, cell, segment], and the cell of each asked option and SKU; one with no
    rows reads zero.
    """
    skus = {sku_id: k for k, sku_id in enumerate(economics.base_price)}
    segments = {segment: k for k, segment in enumerate(SEGMENT_NAMES)}
    week = paths["week_id"].to_numpy(dtype=np.intp)
    kept = (week >= weeks.start) & (week < weeks.stop)
    paths = paths[kept]
    week = week[kept] - weeks.start
    sku = np.array([skus[str(sku_id)] for sku_id in paths["sku_id"]], dtype=np.intp)
    segment = np.array([segments[str(name)] for name in paths["segment"]], dtype=np.intp)
    base_price = np.array(list(economics.base_price.values()))[sku]
    unit_cost = np.array(list(economics.unit_cost.values()))[sku]
    units = paths["units"].to_numpy(dtype=float)
    price = paths["price"].to_numpy(dtype=float)
    baseline_units = paths["baseline_units"].to_numpy(dtype=float)
    change = units * (price - unit_cost) - baseline_units * (base_price - unit_cost)

    codes = paths["option"].to_numpy(dtype=np.intp) * len(skus) + sku
    keys, cell = np.unique(codes, return_inverse=True)
    grid = np.zeros((len(weeks), len(keys) + 1, len(SEGMENT_NAMES)))
    np.add.at(grid, (week, cell, segment), change)
    cumulative = np.concatenate([np.zeros((1, *grid.shape[1:])), np.cumsum(grid, axis=0)])

    asked = options * len(skus) + np.array([skus[sku_id] for sku_id in sku_ids], dtype=np.intp)
    at = np.searchsorted(keys, asked)
    found = at < len(keys)
    found[found] = keys[at[found]] == asked[found]
    return cumulative, np.where(found, at, len(keys))


def _in_segment(window: np.ndarray, segment: np.ndarray) -> np.ndarray:
    """Each row's total in its segment, or over every segment for All customers."""
    everyone = segment == len(SEGMENT_NAMES)
    one = np.minimum(segment, len(SEGMENT_NAMES) - 1)
    return np.where(everyone, window.sum(axis=1), window[np.arange(len(segment)), one])


def _substitutes(line: PlanLine, other: PlanLine, relations: RelationLookup) -> bool:
    """Whether a SKU of one line is a detected substitute of a SKU of the other."""
    return any(
        partner in set(relations.substitutes(sku_id)["sku_id"])
        for sku_id in line.skus
        for partner in other.skus
    )


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

    def margin(self, sku_id: str) -> float:
        """Base price minus unit cost of one SKU."""
        return self.base_price[sku_id] - self.unit_cost[sku_id]


def _weeks(line: PlanLine) -> list[int]:
    return list(range(line.start_week, line.start_week + line.duration_weeks))


def _segments(line: PlanLine) -> list[str]:
    if line.target_segment is TargetSegment.ALL_CUSTOMERS:
        return [segment.value for segment in Segment]
    return [line.target_segment.value]
