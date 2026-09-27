"""Monte Carlo simulation of a promo plan (SPEC §9.5, F-06 AC3, F-09, ADR 0042).

Each run samples every promo response term of every SKU from N(estimate, std error), once per
SKU and run, shared by all its regions, stores, weeks and segments. It then samples units per
store x segment x promo week from a negative binomial around the sampled mean, with the SKU's
fitted size (ADR 0024). Each plan line is simulated on its own SKUs, as `predict` predicts it:
no cross effects between lines.

Within a run, each of a line's SKUs sells at most its pooled available stock in the region over
the line's promo weeks, the oracle's stock basis (ADR 0004, ADR 0011, ADR 0017). The run is a
stock-out for the line when demand reaches that stock. Money follows the units sold, through
the shared economics (ADR 0005, ADR 0015).

With a competitor reaction (F-09 AC2, ADR 0045), each run draws, for each plan line on its own,
whether the competitor matches our discount. A matched competitor cuts its price by the share each
row's customers get off our base price, so the row's competitor term log(cp / p) - log r loses
log(base price / p): the promotion no longer gains on the competitor.

Randomness comes from one seed. The terms, then the noise line by line in plan order, come from
a generator seeded with `seed`; the reaction draws come from a second generator of the same
seed, so omitting the scenario, or a match probability of 0, leaves every other draw as it was.
The same plan, inputs, seed and scenario give identical results.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from promopilot.domain import (
    CompanyPolicy,
    CompetitorReaction,
    LineSimulation,
    Percentiles,
    PlanLine,
    PlanSimulation,
    PromoPlan,
    Region,
    RegionStockout,
    SimulatedOutcomes,
)
from promopilot.economics import fixed_marketing_cost, gross_profit
from promopilot.models.demand import COMPETITOR_TERM, PredictionContext, ResponseRows

Array = NDArray[np.float64]

DEFAULT_RUNS = 1_000
"""SPEC F-09 AC1."""
MIN_RUNS = 100
MAX_RUNS = 5_000
"""The run counts the planner's tool and the API accept (ADR 0042)."""
QUANTILES = (0.1, 0.5, 0.9)
REACTION_STREAM = 1
"""The competitor reaction's generator is seeded with (seed, REACTION_STREAM) (ADR 0045)."""


class ResponseSource(Protocol):
    """What the simulator samples from (`promopilot.models.demand.DemandModel`)."""

    def response_rows(
        self, options: Sequence[PlanLine], context: PredictionContext
    ) -> ResponseRows: ...


@dataclass(frozen=True)
class SimulationSettings:
    """How a planning session simulates each plan revision (SIMULATION_RUNS, SIMULATION_SEED)."""

    n_runs: int
    seed: int


@dataclass(frozen=True)
class SimulationInputs:
    demand: ResponseSource
    stock: pd.DataFrame
    """Pooled stock per SKU and region: sku_id, region and available_stock, as
    `pooled_stock` returns it. A SKU with no row, or a negative figure, has none."""
    policy: CompanyPolicy


@dataclass(frozen=True)
class _Runs:
    """One line's per-run figures."""

    units: Array
    revenue: Array
    gross_profit: Array
    promo_spend: Array
    available: float
    stockout: NDArray[np.bool_]


def simulate(
    plan: PromoPlan,
    inputs: SimulationInputs,
    *,
    n_runs: int,
    seed: int,
    competitor_reaction: CompetitorReaction | None = None,
) -> PlanSimulation:
    """P10/P50/P90 of each plan line's and the plan's outcomes, and stock-out probabilities,
    optionally with the competitor matching each line's discount at random (ADR 0045).

    Raises ValueError for a plan line the demand model cannot predict.
    """
    if n_runs < 1:
        raise ValueError("n_runs must be at least 1")
    rng = np.random.default_rng(seed)
    lines = plan.lines
    if not lines:
        zeros = np.zeros(n_runs)
        return PlanSimulation(
            n_runs=n_runs,
            seed=seed,
            competitor_reaction=competitor_reaction,
            total=_outcomes(zeros, zeros, zeros, zeros, None),
        )
    response = inputs.demand.response_rows(lines, PredictionContext(policy=inputs.policy))
    terms = _sampled_terms(response, n_runs, rng)
    matched = _matched(competitor_reaction, n_runs, len(lines), seed)
    competitor = _competitor_column(response)
    available = _available(inputs.stock)
    groups = response.rows.groupby(["option", "sku_id"], sort=False).indices
    design = response.design.to_numpy(dtype=float)
    runs = [
        _simulate_line(
            planned,
            [(sku_id, np.asarray(groups[(n, sku_id)])) for sku_id in planned.skus],
            response.rows,
            design,
            terms,
            None if matched is None or competitor is None else (matched[:, n], competitor),
            available,
            inputs.policy,
            rng,
        )
        for n, planned in enumerate(lines)
    ]
    return PlanSimulation(
        n_runs=n_runs,
        seed=seed,
        competitor_reaction=competitor_reaction,
        lines=tuple(
            LineSimulation(
                sku_id=planned.sku_id,
                region=planned.region,
                stockout_probability=float(line_runs.stockout.mean()),
                **_outcomes(
                    line_runs.units,
                    line_runs.revenue,
                    line_runs.gross_profit,
                    line_runs.promo_spend,
                    _sell_through([line_runs]),
                ).model_dump(),
            )
            for planned, line_runs in zip(lines, runs, strict=True)
        ),
        total=_outcomes(
            np.sum([r.units for r in runs], axis=0),
            np.sum([r.revenue for r in runs], axis=0),
            np.sum([r.gross_profit for r in runs], axis=0),
            np.sum([r.promo_spend for r in runs], axis=0),
            _sell_through(runs),
        ),
        regions=_region_stockouts(lines, runs),
    )


def _region_stockouts(lines: Sequence[PlanLine], runs: list[_Runs]) -> tuple[RegionStockout, ...]:
    """The share of runs in which at least one of a region's lines ran out, in Region order."""
    stockouts: dict[Region, list[NDArray[np.bool_]]] = {}
    for planned, line_runs in zip(lines, runs, strict=True):
        stockouts.setdefault(planned.region, []).append(line_runs.stockout)
    return tuple(
        RegionStockout(
            region=region,
            stockout_probability=float(np.any(stockouts[region], axis=0).mean()),
        )
        for region in Region
        if region in stockouts
    )


@dataclass(frozen=True)
class _Terms:
    sku_index: dict[str, int]
    values: Array
    """(runs, SKUs, terms): each run's sampled terms."""
    dispersion: Array


def _sampled_terms(response: ResponseRows, n_runs: int, rng: np.random.Generator) -> _Terms:
    columns = list(response.design.columns)
    sku_ids = list(response.estimate.index)
    estimate = response.estimate[columns].to_numpy(dtype=float)
    std_error = response.std_error.loc[sku_ids, columns].to_numpy(dtype=float)
    noise = rng.standard_normal((n_runs, *estimate.shape))
    return _Terms(
        sku_index={sku_id: k for k, sku_id in enumerate(sku_ids)},
        values=estimate + std_error * noise,
        dispersion=response.dispersion.loc[sku_ids].to_numpy(dtype=float),
    )


def _matched(
    reaction: CompetitorReaction | None, n_runs: int, n_lines: int, seed: int
) -> NDArray[np.bool_] | None:
    """(runs, lines): whether the competitor matches each line's discount in each run, drawn
    independently per line from the reaction's own generator; None without a scenario."""
    if reaction is None:
        return None
    draws = np.random.default_rng([seed, REACTION_STREAM]).random((n_runs, n_lines))
    return np.asarray(draws < reaction.match_probability)


def _competitor_column(response: ResponseRows) -> int | None:
    """The competitor term's position among the design columns; None if the model has none."""
    columns = list(response.design.columns)
    return columns.index(COMPETITOR_TERM) if COMPETITOR_TERM in columns else None


def _available(stock: pd.DataFrame) -> dict[tuple[str, str], float]:
    return {
        (str(sku_id), str(region)): max(float(units), 0.0)
        for sku_id, region, units in stock[["sku_id", "region", "available_stock"]].itertuples(
            index=False, name=None
        )
    }


def _simulate_line(
    planned: PlanLine,
    positions: list[tuple[str, NDArray[np.intp]]],
    rows: pd.DataFrame,
    design: Array,
    terms: _Terms,
    reaction: tuple[NDArray[np.bool_], int] | None,
    available: dict[tuple[str, str], float],
    policy: CompanyPolicy,
    rng: np.random.Generator,
) -> _Runs:
    n_runs = terms.values.shape[0]
    units = revenue = profit = funding = np.zeros(n_runs)
    stockout = np.zeros(n_runs, dtype=bool)
    anchor_stock = 0.0
    for sku_id, at in positions:
        sku = rows.iloc[at]
        k = terms.sku_index[sku_id]
        covariates = design[at]
        price = sku["price"].to_numpy(dtype=float)
        base_price = sku["base_price"].to_numpy(dtype=float)
        exponent = terms.values[:, k, :] @ covariates.T
        if reaction is not None:
            # In a matched run the competitor takes its price down by our discount, so the
            # competitor term loses gamma x log(base price / p) on every row (ADR 0045).
            matched, column = reaction
            gamma = np.where(matched, terms.values[:, k, column], 0.0)
            exponent = exponent - np.outer(gamma, np.log(base_price / price))
        means = sku["baseline_units"].to_numpy(dtype=float) * np.exp(exponent)
        size = terms.dispersion[k]
        draws = rng.negative_binomial(size, size / (size + means)).astype(float)
        demand = draws.sum(axis=1)
        stock = available.get((sku_id, planned.region.value), 0.0)
        sold = np.minimum(demand, stock)
        share = np.divide(sold, demand, out=np.zeros_like(sold), where=demand > 0)
        unit_cost = sku["unit_cost"].to_numpy(dtype=float)
        revenue = revenue + share * (draws @ price)
        profit = profit + share * (draws @ gross_profit(1.0, price, unit_cost))
        funding = funding + share * (draws @ (base_price - price))
        stockout = stockout | (demand >= stock)
        if sku_id == planned.sku_id:
            units = sold
            anchor_stock = stock
    fixed = fixed_marketing_cost(planned.mechanism, planned.duration_weeks, policy)
    return _Runs(
        units=units,
        revenue=revenue,
        gross_profit=profit,
        promo_spend=funding + fixed,
        available=anchor_stock,
        stockout=stockout,
    )


def _sell_through(runs: list[_Runs]) -> Array | None:
    """Units sold over the available stock of the lines that have any."""
    stocked = [r for r in runs if r.available > 0]
    if not stocked:
        return None
    return np.asarray(
        np.sum([r.units for r in stocked], axis=0) / sum(r.available for r in stocked)
    )


def _outcomes(
    units: Array, revenue: Array, profit: Array, spend: Array, sell_through: Array | None
) -> SimulatedOutcomes:
    margin = np.divide(profit, revenue, out=np.zeros_like(profit), where=revenue > 0)
    return SimulatedOutcomes(
        units=_percentiles(units),
        revenue=_percentiles(revenue),
        gross_profit=_percentiles(profit),
        margin=_percentiles(margin),
        promo_spend=_percentiles(spend),
        sell_through=None if sell_through is None else _percentiles(sell_through),
    )


def _percentiles(values: Array) -> Percentiles:
    # Interpolated quantiles can break p10 <= p50 <= p90 by an ulp; the running max cannot.
    p10, p50, p90 = np.maximum.accumulate(np.quantile(values, QUANTILES))
    return Percentiles(p10=float(p10), p50=float(p50), p90=float(p90))
