"""The CP-SAT optimiser (SPEC §9.4, ADR 0036): select the promo plan from a candidate set.

`solve` picks at most one plan line per SKU per region, a BUNDLE's partner included (ADR
0014), to maximise the single profit objective (ADR 0005) in integer paise:

    sum of x_o * value_o  -  sum of y_ij * pairwise_ij

where value is the option's worth if it runs alone (incremental profit - cannibalisation +
halo + clearance value, ADR 0035) and pairwise_ij is what two selected options lose together
beyond that (ADR 0033), charged through y_ij = x_i AND x_j. Subject to:

- total promo cost within the marketing budget;
- blended expected margin at least the minimum margin, never below the company-policy
  margin floor (ADR 0007), as sum of x_o * (minimum x revenue_o - gross_profit_o) <= 0;
- at most the company-policy number of promoted SKUs per category per region, a BUNDLE's
  partner counting in its own category (ADR 0028).

Only options worth at least one paisa alone are eligible, so every plan line pays for
itself or is a clearance SKU whose clearance value justifies it (F-01 AC1). An eligible
option must also keep every per-line rule: P90 units within available stock (a BUNDLE's
partner too, ADR 0004), inside the promo window, no deeper than the maximum discount and not
below unit cost unless overstocked (ADR 0007). Costs are rounded up and the budget down to
whole paise, so every plan the solver accepts also passes `validate_plan` (ADR 0012).

The solver runs with a fixed seed and, by default, one worker; with more workers it
interleaves their search, so the same input gives the same plan whenever the solver proves
optimality within its time limit.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
from ortools.sat.python import cp_model

from promopilot.domain import (
    CompanyPolicy,
    PlanLine,
    PlanningRequest,
    PromoPlan,
    Region,
    TargetSegment,
)
from promopilot.economics import effective_unit_price
from promopilot.guardrails import SkuFacts
from promopilot.optimizer.options import PromoOptions

PAISE = 100
_EPSILON = 1e-9
_ROUNDING = 1e-6
"""Paise lost to float noise before rounding a coefficient up or down."""


class SolveStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    """The plan is proven best."""
    FEASIBLE = "FEASIBLE"
    """The time limit ran out first: the best plan found, not proven best."""
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True)
class SolverSettings:
    """The solver's time limit and worker count (OPTIMIZER_TIME_LIMIT_SECONDS,
    OPTIMIZER_WORKERS)."""

    time_limit_seconds: float = 10.0
    workers: int = 1

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("the solver's time limit must be positive")
        if self.workers < 1:
            raise ValueError("the solver needs at least one worker")


class OptionFacts(Protocol):
    """What selection needs beyond the options' own numbers (`FittedOptionFacts`)."""

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        """A SKU's category, prices and overstock flag in a region."""
        ...

    def pairwise_cannibalisation(
        self, pairs: Sequence[tuple[PlanLine, PlanLine]]
    ) -> Sequence[float] | np.ndarray:
        """What each pair of lines loses together beyond their single-line figures (rupees,
        ADR 0033)."""
        ...


@dataclass(frozen=True)
class OptimisationResult:
    """The selected promo plan and how it was found. Money in rupees."""

    status: SolveStatus
    objective: float
    """Selected values less the pairwise cannibalisation of selected pairs, to the paisa."""
    plan: PromoPlan
    selected: tuple[int, ...]
    """The plan lines' rows in the candidate set's table, in candidate order."""
    pairwise_cannibalisation: float
    """The pairwise terms charged for the selected pairs (negative when they gain)."""
    eligible: int
    """Options worth at least a paisa alone that keep every per-line rule."""
    pairs: int
    """Pairs of eligible options with a pairwise term."""


def solve(
    request: PlanningRequest,
    options: PromoOptions,
    facts: OptionFacts,
    policy: CompanyPolicy,
    *,
    settings: SolverSettings | None = None,
    seed: int,
) -> OptimisationResult:
    """The promo plan that maximises the objective for the planning request (ADR 0036)."""
    settings = settings or SolverSettings()
    eligible = _eligible(request, options, facts, policy)
    lines = [options.lines[n] for n in eligible]
    table = options.table.iloc[eligible]
    value = np.rint(table["value"].to_numpy(float) * PAISE).astype(np.int64)
    pairs, charges = _pairs(lines, facts)

    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{n}") for n in range(len(lines))]
    occupied: defaultdict[tuple[str, Region], list[cp_model.IntVar]] = defaultdict(list)
    promoted: defaultdict[tuple[str, Region], list[cp_model.IntVar]] = defaultdict(list)
    for chosen, line in zip(x, lines, strict=True):
        for sku_id in line.skus:
            occupied[(sku_id, line.region)].append(chosen)
            promoted[(facts.sku(sku_id, line.region).category, line.region)].append(chosen)
    for variables in occupied.values():
        model.add_at_most_one(variables)
    for variables in promoted.values():
        model.add(sum(variables) <= policy.max_promoted_skus_per_category_per_region)

    cost = _paise_up(table["promo_cost"].to_numpy(float))
    model.add(_dot(cost, x) <= math.floor(request.marketing_budget * PAISE + _ROUNDING))
    minimum = max(request.min_margin or 0.0, policy.margin_floor)
    short = minimum * table["revenue"].to_numpy(float) - table["gross_profit"].to_numpy(float)
    model.add(_dot(_paise_up(short), x) <= 0)

    y = []
    for i, j in pairs:
        both = model.new_bool_var(f"y{i}_{j}")
        model.add_bool_and([x[i], x[j]]).only_enforce_if(both)
        model.add_bool_or([x[i].Not(), x[j].Not()]).only_enforce_if(both.Not())
        y.append(both)
    model.maximize(_dot(np.concatenate([value, -charges]), [*x, *y]))

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_workers = settings.workers
    solver.parameters.interleave_search = settings.workers > 1
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    status = solver.solve(model)
    if status == cp_model.INFEASIBLE:
        return OptimisationResult(SolveStatus.INFEASIBLE, 0.0, PromoPlan(), (), 0.0, len(lines), 0)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # No plan found in time. The empty plan keeps every constraint here (#36 adds
        # clearance targets, which it may not).
        return OptimisationResult(SolveStatus.FEASIBLE, 0.0, PromoPlan(), (), 0.0, len(lines), 0)

    picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
    charged = int(sum(c for c, both in zip(charges, y, strict=True) if solver.boolean_value(both)))
    return OptimisationResult(
        status=SolveStatus.OPTIMAL if status == cp_model.OPTIMAL else SolveStatus.FEASIBLE,
        objective=(int(value[picked].sum()) - charged) / PAISE,
        plan=PromoPlan(lines=tuple(lines[n] for n in picked)),
        selected=tuple(eligible[n] for n in picked),
        pairwise_cannibalisation=charged / PAISE,
        eligible=len(lines),
        pairs=len(pairs),
    )


def _eligible(
    request: PlanningRequest, options: PromoOptions, facts: OptionFacts, policy: CompanyPolicy
) -> list[int]:
    """Options worth at least one paisa alone that keep every per-line rule, in order."""
    table = options.table
    worth = np.rint(table["value"].to_numpy(float) * PAISE) >= 1
    fits = table["p90_units"].to_numpy(float) <= table["available_stock"].to_numpy(float) + _EPSILON
    partner_fits = (
        table["partner_p90_units"].to_numpy(float)
        <= table["partner_available_stock"].to_numpy(float) + _EPSILON
    )
    window = request.promo_window
    kept = []
    for n in np.flatnonzero(worth & fits):
        line = options.lines[n]
        if line.bundle_partner_sku_id is not None and not partner_fits[n]:
            continue
        end_week = line.start_week + line.duration_weeks - 1
        if line.start_week < window.start_week or end_week > window.end_week:
            continue
        if _priced_within_policy(line, facts, policy):
            kept.append(int(n))
    return kept


def _priced_within_policy(line: PlanLine, facts: OptionFacts, policy: CompanyPolicy) -> bool:
    """No deeper than the maximum discount, and no SKU below unit cost unless overstocked."""
    for sku_id in line.skus:
        sku = facts.sku(sku_id, line.region)
        price = effective_unit_price(line.mechanism, sku.base_price, line.depth_pct)
        if (
            sku_id == line.sku_id
            and 1 - price / sku.base_price > policy.max_discount_pct / 100 + _EPSILON
        ):
            return False
        if price < sku.unit_cost - _EPSILON and not sku.overstocked:
            return False
    return True


def _pairs(
    lines: Sequence[PlanLine], facts: OptionFacts
) -> tuple[list[tuple[int, int]], np.ndarray]:
    """The pairs of lines that could run together, with a pairwise term in whole paise."""
    candidates = [
        (i, j) for i, j in _overlapping(lines) if not set(lines[i].skus) & set(lines[j].skus)
    ]
    if not candidates:
        return [], np.zeros(0, dtype=np.int64)
    terms = facts.pairwise_cannibalisation([(lines[i], lines[j]) for i, j in candidates])
    charges = np.rint(np.asarray(terms, dtype=float) * PAISE).astype(np.int64)
    keep = np.flatnonzero(charges != 0)
    return [candidates[k] for k in keep], charges[keep]


def _overlapping(lines: Sequence[PlanLine]) -> list[tuple[int, int]]:
    """Pairs in the same region with a week and a target segment in common."""
    by_region: defaultdict[Region, list[int]] = defaultdict(list)
    for n, line in enumerate(lines):
        by_region[line.region].append(n)
    everyone = TargetSegment.ALL_CUSTOMERS
    found = []
    for members in by_region.values():
        for k, i in enumerate(members):
            a = lines[i]
            for j in members[k + 1 :]:
                b = lines[j]
                if a.start_week + a.duration_weeks <= b.start_week:
                    continue
                if b.start_week + b.duration_weeks <= a.start_week:
                    continue
                if everyone in (a.target_segment, b.target_segment) or (
                    a.target_segment is b.target_segment
                ):
                    found.append((i, j))
    return found


def _paise_up(rupees: np.ndarray) -> np.ndarray:
    """Rupees in whole paise, rounded up: a constraint on them is never looser than exact."""
    return np.ceil(rupees * PAISE - _ROUNDING).astype(np.int64)


def _dot(coefficients: np.ndarray, variables: Sequence[cp_model.IntVar]) -> cp_model.LinearExpr:
    return cp_model.LinearExpr.weighted_sum(variables, [int(c) for c in coefficients])
