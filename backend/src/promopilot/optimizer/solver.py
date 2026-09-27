"""The CP-SAT optimiser (SPEC §9.4, ADR 0036): select the promo plan from a candidate set.

`solve` picks at most one plan line per SKU per region, a BUNDLE's partner included (ADR
0014), to maximise the single profit objective (ADR 0005) in integer paise:

    sum of x_o * value_o  -  sum of y_ij * pairwise_ij

where value is the option's worth if it runs alone (incremental profit - cannibalisation +
halo + clearance value, ADR 0035) and pairwise_ij is what two selected options lose together
beyond that (ADR 0033), charged through y_ij = x_i AND x_j. Subject to plan-level
constraints, each a linear `sum of x_o * a_o <= b` in whole paise or thousandths of a unit:

- total promo cost within the marketing budget, and within each regional budget cap the
  brief sets (ADR 0040);
- blended expected margin at least the minimum margin, never below the company-policy
  margin floor (ADR 0007), as sum of x_o * (minimum x revenue_o - gross_profit_o) <= 0;
- at most the promoted-SKU cap per category per region (company policy's, or the brief's
  where tighter), a BUNDLE's partner counting in its own category (ADR 0028);
- each clearance target: a SKU the brief names for clearance sells at least the target
  share of its available stock over the promo window in each region (ADR 0014, ADR 0040);
- when enabled, no KVI promo price more than the tolerance above the competitor's (ADR
  0031).

A brief may only tighten company policy; `plan_limits` applies it and reports what it did not
apply (ADR 0007). Only options worth at least one paisa alone are eligible, or that sell more
of a SKU towards its clearance target, so every plan line pays for itself, is a clearance SKU
whose clearance value justifies it (F-01 AC1), or is needed for a clearance target the brief
set. An eligible option must also keep every per-line rule: P90 units within available stock
(a BUNDLE's partner too, ADR 0004), inside the promo window, no deeper than the maximum
discount and not below unit cost unless overstocked (ADR 0007); a SKU named for clearance is
overstocked. Costs are rounded up and the budgets down to whole paise, and units sold towards a
target down, so every plan the solver accepts also passes `validate_plan` (ADR 0012).

With clearance targets the solve has two phases (ADR 0040). The first finds the plan closest to
every target, the least stock left short of target weighted by unit cost, under every other
constraint. Each target is then lowered to what that plan reaches, and the second phase
maximises the objective. When every target is reachable this is exactly the hard model; when
one is not, the plan comes as close as any can and `clearance_shortfalls` reports by how much
it falls short. The empty plan is always feasible in the first phase, so there is always a
plan to return, even when no better one is found in time.

Beside the plan, `solve` reports (ADR 0038):

- the binding constraints: each plan-level constraint whose removal gives a strictly better
  objective, proven by a static bound (cannot bind), a better plan one swap away (binds) or a
  re-solve without it (either), within their own time limit; one left unsettled when the
  time runs out is reported unproven;
- why each plan line was chosen: the positive parts of its value, the units it adds towards
  a clearance target, and whether it is the best eligible option of its SKU and region;
- the best option of up to five SKUs and regions with no plan line, with every rule it
  breaks alone or added to the plan.

The solver runs with a fixed seed and, by default, one worker; with more workers it
interleaves their search, so the same input gives the same plan whenever the solver proves
optimality within its time limit.
"""

import math
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import numpy as np
from ortools.sat.python import cp_model

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ClearanceShortfall,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    NotSelectedOption,
    NotSelectedReason,
    PlanLine,
    PlanningRequest,
    PolicyFinding,
    PromoPlan,
    Region,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    TargetSegment,
    WhyChosen,
)
from promopilot.economics import effective_unit_price
from promopilot.guardrails import PlanLimits, SkuFacts, plan_limits
from promopilot.optimizer.options import ClearanceBaseline, PromoOptions

PAISE = 100
MILLI_UNITS = 1000
"""Clearance constraints count units in thousandths: CP-SAT needs whole numbers."""
_EPSILON = 1e-9
_ROUNDING = 1e-6
"""Paise (or thousandths of a unit) lost to float noise before rounding up or down."""
_MIN_RESOLVE_SECONDS = 0.001
"""Less binding time left than this settles no more constraints."""


@dataclass(frozen=True)
class SolverSettings:
    """The solver's time limit and worker count (OPTIMIZER_TIME_LIMIT_SECONDS,
    OPTIMIZER_WORKERS), and the time shared by the re-solves that find binding constraints
    (OPTIMIZER_BINDING_TIME_LIMIT_SECONDS, ADR 0038)."""

    time_limit_seconds: float = 10.0
    workers: int = 1
    binding_time_limit_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("the solver's time limit must be positive")
        if self.workers < 1:
            raise ValueError("the solver needs at least one worker")
        if self.binding_time_limit_seconds < 0:
            raise ValueError("the binding time limit cannot be negative")


class OptionFacts(Protocol):
    """What selection needs beyond the options' own numbers (`FittedOptionFacts`)."""

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        """A SKU's category, prices, overstock flag and competitor price in a region."""
        ...

    def pairwise_cannibalisation(
        self, pairs: Sequence[tuple[PlanLine, PlanLine]]
    ) -> Sequence[float] | np.ndarray:
        """What each pair of lines loses together beyond their single-line figures (rupees,
        ADR 0033)."""
        ...


@dataclass(frozen=True)
class OptimisationResult:
    """The selected promo plan, how it was found and why (ADR 0036, ADR 0038, ADR 0040).
    Money in rupees."""

    status: SolveStatus
    objective: float
    """Selected values less the pairwise cannibalisation of selected pairs, to the paisa."""
    plan: PromoPlan
    selected: tuple[int, ...]
    """The plan lines' rows in the candidate set's table, in candidate order."""
    pairwise_cannibalisation: float
    """The pairwise terms charged for the selected pairs (negative when they gain)."""
    eligible: int
    """Options the plan could select: worth at least a paisa alone or needed for a clearance
    target, keeping every per-line rule and the KVI price tolerance."""
    pairs: int
    """Pairs of eligible options with a pairwise term."""
    binding_constraints: tuple[BindingConstraint, ...] = ()
    """Constraints whose removal gives a strictly better objective, or may (unproven)."""
    why_chosen: tuple[WhyChosen, ...] = ()
    """One per plan line, in the plan's order."""
    not_selected: tuple[NotSelectedOption, ...] = ()
    """The best option of up to NOT_SELECTED_SHOWN SKUs and regions with no plan line."""
    clearance_shortfalls: tuple[ClearanceShortfall, ...] = ()
    """Clearance targets no plan within the other constraints reaches, and by how much this
    plan misses them."""
    policy_findings: tuple[PolicyFinding, ...] = ()
    """Brief values that would have loosened company policy, which was applied instead."""


NOT_SELECTED_SHOWN = 5


def solve(
    request: PlanningRequest,
    options: PromoOptions,
    facts: OptionFacts,
    policy: CompanyPolicy,
    *,
    settings: SolverSettings | None = None,
    seed: int,
) -> OptimisationResult:
    """The promo plan that maximises the objective for the planning request (ADR 0036), as
    close to its clearance targets as any plan can be (ADR 0040), with its binding
    constraints, why each line was chosen and the best options left out (ADR 0038)."""
    settings = settings or SolverSettings()
    started = time.monotonic()
    problem = _Problem.of(request, options, facts, policy)
    findings = problem.rules.findings
    closest: _Closest | None = None
    time_limit = settings.time_limit_seconds
    if problem.targets:
        closest = problem.closest(settings, seed, time_limit=time_limit / 2)
        problem = problem.lowered(closest.shortfall)
        time_limit = max(time_limit - (time.monotonic() - started), time_limit / 2)
    outcome = problem.solve(
        settings, seed, hint=closest.picked if closest else (), time_limit=time_limit
    )
    if outcome.status == cp_model.INFEASIBLE:
        return OptimisationResult(
            SolveStatus.INFEASIBLE,
            0.0,
            PromoPlan(),
            (),
            0.0,
            problem.choosable,
            0,
            policy_findings=findings,
        )
    found = outcome.status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # No plan found in time: the closest plan keeps every constraint, the lowered targets
    # included; without targets the empty plan does.
    picked = outcome.picked if found else (closest.picked if closest else [])
    charged = outcome.charged if found else problem.charged(picked)
    proven = outcome.status == cp_model.OPTIMAL and (closest is None or closest.proven)
    status = SolveStatus.OPTIMAL if proven else SolveStatus.FEASIBLE
    objective = int(problem.value[picked].sum()) - charged
    return OptimisationResult(
        status=status,
        objective=objective / PAISE,
        plan=PromoPlan(lines=tuple(problem.lines[n] for n in picked)),
        selected=tuple(problem.eligible[n] for n in picked),
        pairwise_cannibalisation=charged / PAISE,
        eligible=problem.choosable,
        pairs=len(problem.pairs) if found or closest else 0,
        binding_constraints=(
            problem.binding(picked, objective, settings, seed) if proven else problem.unproven()
        ),
        why_chosen=tuple(problem.why_chosen(n) for n in picked),
        not_selected=problem.not_selected(picked),
        clearance_shortfalls=problem.shortfalls(picked),
        policy_findings=findings,
    )


@dataclass(frozen=True)
class _Limit:
    """One plan-level constraint of the model."""

    kind: ConstraintKind
    category: str | None = None
    """For a promoted-SKU cap."""
    region: Region | None = None
    """For a promoted-SKU cap, a regional budget cap or a clearance target."""
    sku_id: str | None = None
    """For a clearance target."""


_BUDGET = _Limit(ConstraintKind.MARKETING_BUDGET)
_MARGIN = _Limit(ConstraintKind.MINIMUM_MARGIN)
_KVI = _Limit(ConstraintKind.KVI_PRICE_TOLERANCE)

_REASONS = {
    ConstraintKind.MARKETING_BUDGET: NotSelectedReason.OVER_BUDGET,
    ConstraintKind.REGIONAL_BUDGET: NotSelectedReason.OVER_REGIONAL_BUDGET,
    ConstraintKind.MINIMUM_MARGIN: NotSelectedReason.BREAKS_MARGIN,
    ConstraintKind.CLEARANCE_TARGET: NotSelectedReason.MISSES_CLEARANCE_TARGET,
    ConstraintKind.KVI_PRICE_TOLERANCE: NotSelectedReason.BREAKS_KVI_TOLERANCE,
}
"""The not-selected reason for adding an option that breaks a constraint (the promoted-SKU
cap has its own check, `_over_cap`)."""


@dataclass(frozen=True)
class _Target:
    """A clearance target in one region: the baseline and stock it is measured against."""

    baseline: ClearanceBaseline
    sell_through: float
    unit_cost: float

    @property
    def need(self) -> float:
        """Units the plan must add over the promo window, beyond the baseline."""
        return self.sell_through * self.baseline.available_stock - self.baseline.baseline_units


@dataclass(frozen=True)
class _Outcome:
    status: cp_model.CpSolverStatus
    picked: list[int]
    """Selected eligible options, as indices into `_Problem.lines`."""
    charged: int
    """Pairwise terms of selected pairs, in paise."""


@dataclass(frozen=True)
class _Closest:
    """The first phase with clearance targets: the plan closest to every target."""

    picked: list[int]
    shortfall: dict[_Limit, int]
    """Thousandths of a unit short of each target."""
    proven: bool
    """Whether no plan is proven closer."""


def out_of_near(near: np.ndarray, clash: np.ndarray) -> np.ndarray:
    """Option o's pairwise terms with what each swap takes out: its clashes, then line r."""
    base = np.where(clash, near, 0).sum(axis=1)
    extra = np.where(clash, 0, near)
    return np.concatenate([base[:, None] + extra, base[:, None]], axis=1)


@dataclass(frozen=True)
class _Swaps:
    """Every swap of one option into a plan, scored: rows are options, columns the one
    extra plan line taken out (the last column: none)."""

    plan: list[int]
    clash: np.ndarray
    gain: np.ndarray
    after: np.ndarray
    """options x (plan lines + 1) x constraints: each constraint's left-hand side after the
    swap."""
    valid: np.ndarray


@dataclass
class _Problem:
    """The eligible options and every coefficient of the model, in whole paise or
    thousandths of a unit."""

    request: PlanningRequest
    options: PromoOptions
    facts: OptionFacts
    policy: CompanyPolicy
    rules: PlanLimits
    cleared: frozenset[str]
    """SKUs the brief names for clearance: overstocked in every region (ADR 0014)."""
    eligible: list[int]
    """Eligible options' rows in the candidate table."""
    lines: list[PlanLine]
    value: np.ndarray
    kvi_breaking: np.ndarray
    """Eligible options that break the KVI price tolerance: in the model, but out of any plan
    unless the tolerance is dropped."""
    limits: list[_Limit]
    coefficients: np.ndarray
    """constraints x eligible options."""
    bound: np.ndarray
    """Each constraint's right-hand side."""
    targets: dict[_Limit, _Target]
    groups: dict[tuple[str, Region], list[int]]
    """(category, region) -> eligible options promoting a SKU there, once per SKU."""
    pairs: list[tuple[int, int]]
    charges: np.ndarray
    terms: dict[tuple[int, int], int]
    """Pairwise terms in paise by candidate-table rows (lower row first): every non-zero
    term between eligible options, and any term asked for since, zero or not."""
    _keys: list[list[tuple[str, Region]]] = field(default_factory=list, init=False)
    """The (SKU, region)s each eligible option occupies."""
    _near: list[dict[int, int]] = field(default_factory=list, init=False)
    """Each eligible option's non-zero pairwise terms, by the other option."""
    _swap_cache: dict[tuple[int, ...], "_Swaps | None"] = field(default_factory=dict, init=False)
    _eligible_rows: set[int] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self._eligible_rows = set(self.eligible)
        self._keys = [[(sku_id, line.region) for sku_id in line.skus] for line in self.lines]
        self._near = [{} for _ in self.lines]
        for (i, j), charge in zip(self.pairs, self.charges, strict=True):
            self._near[i][j] = int(charge)
            self._near[j][i] = int(charge)
        self._swap_cache = {}

    @classmethod
    def of(
        cls,
        request: PlanningRequest,
        options: PromoOptions,
        facts: OptionFacts,
        policy: CompanyPolicy,
    ) -> "_Problem":
        rules = plan_limits(request, policy)
        cleared = frozenset(target.sku_id for target in request.clearance_targets)
        sell_through = {target.sku_id: target.sell_through for target in request.clearance_targets}
        targets = {
            _Limit(ConstraintKind.CLEARANCE_TARGET, region=c.region, sku_id=c.sku_id): _Target(
                baseline=c,
                sell_through=sell_through[c.sku_id],
                unit_cost=facts.sku(c.sku_id, c.region).unit_cost,
            )
            for c in options.clearance
            if c.sku_id in sell_through and c.region in request.scope.regions
        }
        eligible = _eligible(request, options, facts, policy, cleared, targets)
        lines = [options.lines[n] for n in eligible]
        groups: defaultdict[tuple[str, Region], list[int]] = defaultdict(list)
        for n, line in enumerate(lines):
            for sku_id in line.skus:
                groups[(facts.sku(sku_id, line.region).category, line.region)].append(n)
        limits = [
            _BUDGET,
            _MARGIN,
            *(
                _Limit(ConstraintKind.MAX_PROMOTED_SKUS, category=category, region=region)
                for category, region in sorted(groups)
            ),
            *(
                _Limit(ConstraintKind.REGIONAL_BUDGET, region=region)
                for region in Region
                if region in request.regional_budget_caps
            ),
            *sorted(targets, key=_target_order),
            *([_KVI] if rules.kvi_price_tolerance is not None else []),
        ]
        pairs, charges = _pairs(lines, facts)
        problem = cls(
            request=request,
            options=options,
            facts=facts,
            policy=policy,
            rules=rules,
            cleared=cleared,
            eligible=eligible,
            lines=lines,
            value=np.rint(options.table["value"].to_numpy(float)[eligible] * PAISE).astype(
                np.int64
            ),
            kvi_breaking=np.array(
                [_breaks_kvi(line, facts, rules.kvi_price_tolerance) for line in lines], dtype=bool
            ),
            limits=limits,
            coefficients=np.zeros((len(limits), len(lines)), dtype=np.int64),
            bound=np.array([0] * len(limits), dtype=np.int64),
            targets=targets,
            groups=dict(groups),
            pairs=pairs,
            charges=charges,
            terms={
                _key(eligible[i], eligible[j]): int(term)
                for (i, j), term in zip(pairs, charges, strict=True)
            },
        )
        problem.coefficients = problem.row_coefficients(eligible)
        problem.bound = np.array([problem.right_hand_side(limit) for limit in limits], np.int64)
        return problem

    @property
    def choosable(self) -> int:
        """Eligible options a plan may select with every constraint in place."""
        return int((~self.kvi_breaking).sum())

    def row_coefficients(self, rows: Sequence[int]) -> np.ndarray:
        """Each constraint's coefficient for these candidate-table rows (constraints x
        rows), rounded so a plan that keeps them keeps the constraint exactly."""
        table = self.options.table.iloc[list(rows)]
        lines = [self.options.lines[row] for row in rows]
        cost = _paise_up(table["promo_cost"].to_numpy(float))
        short = _paise_up(
            self.rules.min_margin * table["revenue"].to_numpy(float)
            - table["gross_profit"].to_numpy(float)
        )
        anchor_uplift = table["window_uplift"].to_numpy(float)
        partner_uplift = table["partner_window_uplift"].to_numpy(float)
        tolerance = self.rules.kvi_price_tolerance
        categories: dict[tuple[str, Region], str] = {}

        def category(sku_id: str, region: Region) -> str:
            if (sku_id, region) not in categories:
                categories[(sku_id, region)] = self.facts.sku(sku_id, region).category
            return categories[(sku_id, region)]

        found = np.zeros((len(self.limits), len(rows)), dtype=np.int64)
        for k, limit in enumerate(self.limits):
            if limit == _BUDGET:
                found[k] = cost
            elif limit == _MARGIN:
                found[k] = short
            elif limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
                found[k] = [
                    sum(
                        1
                        for sku_id in line.skus
                        if line.region is limit.region
                        and category(sku_id, line.region) == limit.category
                    )
                    for line in lines
                ]
            elif limit.kind is ConstraintKind.REGIONAL_BUDGET:
                found[k] = np.where([line.region is limit.region for line in lines], cost, 0)
            elif limit.kind is ConstraintKind.CLEARANCE_TARGET:
                uplift = np.zeros(len(rows))
                for n, line in enumerate(lines):
                    if line.region is not limit.region:
                        continue
                    if line.sku_id == limit.sku_id:
                        uplift[n] += anchor_uplift[n]
                    if line.bundle_partner_sku_id == limit.sku_id:
                        uplift[n] += partner_uplift[n]
                # Sold units count down, so the target is never met on rounding alone.
                found[k] = -np.floor(uplift * MILLI_UNITS + _ROUNDING).astype(np.int64)
            else:
                found[k] = [_breaks_kvi(line, self.facts, tolerance) for line in lines]
        return found

    def right_hand_side(self, limit: _Limit) -> int:
        if limit == _BUDGET:
            return math.floor(self.request.marketing_budget * PAISE + _ROUNDING)
        if limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            return self.rules.max_promoted_skus
        if limit.kind is ConstraintKind.REGIONAL_BUDGET:
            assert limit.region is not None
            cap = self.request.regional_budget_caps[limit.region]
            return math.floor(cap * PAISE + _ROUNDING)
        if limit.kind is ConstraintKind.CLEARANCE_TARGET:
            return -math.ceil(self.targets[limit].need * MILLI_UNITS - _ROUNDING)
        return 0

    def lowered(self, shortfall: dict[_Limit, int]) -> "_Problem":
        """The same problem with each clearance target lowered by its shortfall."""
        if not any(shortfall.values()):
            return self
        bound = self.bound.copy()
        for k, limit in enumerate(self.limits):
            bound[k] += shortfall.get(limit, 0)
        return replace(self, bound=bound)

    def closest(self, settings: SolverSettings, seed: int, *, time_limit: float) -> _Closest:
        """The plan that leaves the least stock short of the clearance targets, each unit
        weighted by its unit cost, under every other constraint (the first phase)."""
        model = cp_model.CpModel()
        x = self._variables(model)
        slack = []
        for k, limit in enumerate(self.limits):
            expression = _dot(self.coefficients[k], x)
            if limit in self.targets:
                most = max(0, -int(self.bound[k])) + int(np.maximum(self.coefficients[k], 0).sum())
                short = model.new_int_var(0, most, f"s{k}")
                model.add(expression - short <= int(self.bound[k]))
                weight = max(1, round(self.targets[limit].unit_cost * PAISE))
                slack.append((weight, short))
                model.add_hint(short, max(0, -int(self.bound[k])))
            else:
                model.add(expression <= int(self.bound[k]))
        model.minimize(sum(weight * short for weight, short in slack))
        for chosen in x:
            model.add_hint(chosen, False)
        solver = self._solver(settings, seed, time_limit, first=False)
        status = solver.solve(model)
        found = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        picked = [n for n, chosen in enumerate(x) if found and solver.boolean_value(chosen)]
        shortfall = {
            limit: max(0, int(self.coefficients[k, picked].sum()) - int(self.bound[k]))
            for k, limit in enumerate(self.limits)
            if limit in self.targets
        }
        return _Closest(picked, shortfall, status == cp_model.OPTIMAL)

    def solve(
        self,
        settings: SolverSettings,
        seed: int,
        *,
        drop: _Limit | None = None,
        hint: Sequence[int] = (),
        beat: int | None = None,
        time_limit: float | None = None,
        first: bool = False,
        breaking: bool = False,
    ) -> _Outcome:
        """Solve the model, without the `drop` constraint, starting from the `hint` plan,
        within `time_limit` seconds (the time limit of `settings` by default). With `beat`,
        only plans whose objective (paise) is at least that are feasible. With `breaking`,
        only plans that break the `drop` constraint are. With `first`, the search stops at
        the first feasible plan."""
        model = cp_model.CpModel()
        x = self._variables(model)
        for k, limit in enumerate(self.limits):
            expression = _dot(self.coefficients[k], x)
            if limit != drop:
                model.add(expression <= int(self.bound[k]))
            elif breaking:
                model.add(expression >= int(self.bound[k]) + 1)

        y = []
        for i, j in self.pairs:
            both = model.new_bool_var(f"y{i}_{j}")
            model.add_bool_and([x[i], x[j]]).only_enforce_if(both)
            model.add_bool_or([x[i].Not(), x[j].Not()]).only_enforce_if(both.Not())
            y.append(both)
        objective = _dot(np.concatenate([self.value, -self.charges]), [*x, *y])
        if beat is not None:
            model.add(objective >= beat)
        model.maximize(objective)
        if hint:
            hinted = set(hint)
            for n, chosen in enumerate(x):
                model.add_hint(chosen, n in hinted)
            for (i, j), both in zip(self.pairs, y, strict=True):
                model.add_hint(both, i in hinted and j in hinted)

        solver = self._solver(settings, seed, time_limit or settings.time_limit_seconds, first)
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _Outcome(status, [], 0)
        picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
        charged = int(
            sum(c for c, both in zip(self.charges, y, strict=True) if solver.boolean_value(both))
        )
        return _Outcome(status, picked, charged)

    def _variables(self, model: cp_model.CpModel) -> list[cp_model.IntVar]:
        """One x per eligible option, at most one per (SKU, region) it occupies."""
        x = [model.new_bool_var(f"x{n}") for n in range(len(self.lines))]
        occupied: defaultdict[tuple[str, Region], list[cp_model.IntVar]] = defaultdict(list)
        for chosen, keys in zip(x, self._keys, strict=True):
            for key in keys:
                occupied[key].append(chosen)
        for variables in occupied.values():
            model.add_at_most_one(variables)
        return x

    @staticmethod
    def _solver(
        settings: SolverSettings, seed: int, time_limit: float, first: bool
    ) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = seed
        solver.parameters.num_workers = settings.workers
        solver.parameters.interleave_search = settings.workers > 1
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.stop_after_first_solution = first
        return solver

    def charged(self, plan: Sequence[int]) -> int:
        """The pairwise terms of a plan's selected pairs, in paise."""
        return sum(self._near[a].get(b, 0) for a in plan for b in plan if a < b)

    def binding(
        self, picked: list[int], objective: int, settings: SolverSettings, seed: int
    ) -> tuple[BindingConstraint, ...]:
        """Each constraint whose removal gives a strictly better objective (ADR 0038).

        A constraint that no plan could ever break (`_can_bind`) is settled as not binding
        without solving. For the others, a better plan one swap away from the current one
        that keeps every other constraint (`_swap`) proves it binds, with the gain as a
        lower bound. Each constraint still unsettled is re-solved without it, from the
        current plan, for a plan at least a paisa better that breaks it (the plan is optimal
        with it, so any better plan must), and the search stops at the first one found:
        that proves it binds; infeasibility proves it does not. Each gets an even share of
        what is left of the binding time limit, and any time left after that is spent on
        making the lower bounds exact. The pairwise terms are the ones already priced.
        Whatever is still unsettled at the end is unproven.
        """
        limits = self._limits()
        deadline = time.monotonic() + settings.binding_time_limit_seconds
        settled: dict[_Limit, tuple[BindingEvidence, int, list[int]] | None] = {}

        def left() -> float:
            return deadline - time.monotonic()

        for limit in limits:
            if left() < _MIN_RESOLVE_SECONDS:
                break
            swapped = self._swap(picked, limit)
            if swapped is not None:
                reached, better = swapped
                settled[limit] = (BindingEvidence.LOWER_BOUND, reached - objective, better)

        open_ = [limit for limit in limits if limit not in settled]
        for k, limit in enumerate(open_):
            if left() < _MIN_RESOLVE_SECONDS:
                break
            share = min(left() / (len(open_) - k), settings.time_limit_seconds)
            relaxed = self.solve(
                settings,
                seed,
                drop=limit,
                hint=picked,
                beat=objective + 1,
                time_limit=share,
                first=True,
                breaking=True,
            )
            if relaxed.status == cp_model.INFEASIBLE:
                settled[limit] = None
            elif relaxed.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                exact = relaxed.status == cp_model.OPTIMAL
                settled[limit] = (
                    BindingEvidence.EXACT if exact else BindingEvidence.LOWER_BOUND,
                    self._objective(relaxed) - objective,
                    relaxed.picked,
                )

        bounded = [
            limit
            for limit, found in settled.items()
            if found is not None and found[0] is BindingEvidence.LOWER_BOUND
        ]
        for k, limit in enumerate(bounded):
            if left() < _MIN_RESOLVE_SECONDS:
                break
            _, gain, better = settled[limit] or (BindingEvidence.LOWER_BOUND, 0, [])
            relaxed = self.solve(
                settings,
                seed,
                drop=limit,
                hint=better,
                beat=objective + gain,
                breaking=True,
                time_limit=min(left() / (len(bounded) - k), settings.time_limit_seconds),
            )
            if relaxed.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                exact = relaxed.status == cp_model.OPTIMAL
                settled[limit] = (
                    BindingEvidence.EXACT if exact else BindingEvidence.LOWER_BOUND,
                    max(gain, self._objective(relaxed) - objective),
                    relaxed.picked,
                )

        found = []
        for limit in limits:
            if limit not in settled:
                found.append(self._named(limit, BindingEvidence.UNPROVEN, None))
            elif (result := settled[limit]) is not None:
                found.append(self._named(limit, result[0], result[1]))
        return tuple(found)

    def unproven(self) -> tuple[BindingConstraint, ...]:
        """Every constraint that could bind, none settled: the plan itself is not proven
        best, so no gain from dropping one would prove it binds."""
        return tuple(self._named(limit, BindingEvidence.UNPROVEN, None) for limit in self._limits())

    def _swap(self, picked: list[int], drop: _Limit) -> tuple[int, list[int]] | None:
        """The best plan, and its objective, that swaps one option into the current plan,
        taking out the lines it clashes with and at most one more, and is strictly better
        while keeping every constraint but `drop`. None if there is none.

        Any such plan proves `drop` binds, since the current plan is optimal with it. Every
        swap is scored at once on arrays; the best is re-checked from scratch
        (`_evaluate`) before it counts.
        """
        swaps = self._swaps(picked)
        if swaps is None:
            return None
        kept = [k for k, limit in enumerate(self.limits) if limit != drop]
        valid = swaps.valid & (swaps.after[:, :, kept] <= self.bound[kept]).all(axis=2)
        gain = np.where(valid, swaps.gain, 0)
        if gain.max(initial=0) < 1:
            return None
        o, r = np.unravel_index(int(np.argmax(gain)), gain.shape)
        plan_lines = swaps.plan
        out = {plan_lines[c] for c in np.flatnonzero(swaps.clash[o])}
        if r < len(plan_lines):
            out.add(plan_lines[r])
        better = sorted((set(picked) - out) | {int(o)})
        found = self._evaluate(better, drop)
        return None if found is None else (found, better)

    def _swaps(self, picked: list[int]) -> "_Swaps | None":
        """Every swap into the current plan, scored on arrays (cached per plan)."""
        key = tuple(picked)
        if key in self._swap_cache:
            return self._swap_cache[key]
        size, count = len(self.lines), len(picked)
        if size == 0:
            self._swap_cache[key] = None
            return None
        plan = np.array(picked, dtype=np.int64)
        position = {n: k for k, n in enumerate(picked)}
        # clash[o, k]: plan line k occupies a (SKU, region) that option o needs.
        occupant = {key_: position[n] for n in picked for key_ in self._keys[n]}
        clash = np.zeros((size, count), dtype=bool)
        for o in range(size):
            for key_ in self._keys[o]:
                if key_ in occupant:
                    clash[o, occupant[key_]] = True
        # near[o, k]: the pairwise term of option o with plan line k.
        near = np.zeros((size, count), dtype=np.int64)
        for o in range(size):
            for n, charge in self._near[o].items():
                if n in position:
                    near[o, position[n]] = charge
        among = near[plan]  # plan x plan, symmetric, zero diagonal
        inner = among.sum(axis=1)
        clash_i = clash.astype(np.int64)

        def out_of(values: np.ndarray) -> np.ndarray:
            """values summed over what each swap takes out: its clashes, then line r."""
            base = clash_i @ values
            extra = np.where(clash, 0, values[None, :])
            return np.concatenate([base[:, None] + extra, base[:, None]], axis=1)

        value = self.value[plan]
        lost_pairs = (  # pairs among what is taken out, counted once
            np.einsum("ok,kl,ol->o", clash_i, among, clash_i) // 2
        )
        with_r = clash_i @ among  # o x k: pairs of the clashes with line k
        together = np.concatenate([lost_pairs[:, None] + with_r, lost_pairs[:, None]], axis=1)
        own = near.sum(axis=1)
        gain = (
            self.value[:, None]
            - out_of(value)
            + out_of(inner)
            - together
            - (own[:, None] - out_of_near(near, clash))
        )
        in_plan = self.coefficients[:, plan].T  # plan lines x constraints
        now = in_plan.sum(axis=0)
        taken = clash_i @ in_plan  # o x constraints
        extra = np.where(clash[:, :, None], 0, in_plan[None, :, :])  # o x k x constraints
        after = (now + self.coefficients.T - taken)[:, None, :] - np.concatenate(
            [extra, np.zeros((size, 1, len(self.limits)), dtype=np.int64)], axis=1
        )
        valid = np.ones((size, count + 1), dtype=bool)
        valid[:, :count] &= ~clash
        valid[plan, :] = False
        swaps = _Swaps(plan=picked, clash=clash, gain=gain, after=after, valid=valid)
        self._swap_cache[key] = swaps
        return swaps

    def _evaluate(self, plan: list[int], drop: _Limit) -> int | None:
        """The plan's objective in paise if it keeps every constraint but `drop`."""
        keys = [key for n in plan for key in self._keys[n]]
        if len(keys) != len(set(keys)):
            return None
        totals = self.coefficients[:, plan].sum(axis=1)
        for k, limit in enumerate(self.limits):
            if limit != drop and totals[k] > self.bound[k]:
                return None
        return int(self.value[plan].sum()) - self.charged(plan)

    def _objective(self, outcome: _Outcome) -> int:
        return int(self.value[outcome.picked].sum()) - outcome.charged

    def _limits(self) -> list[_Limit]:
        """The constraints that some plan could break (`_can_bind`)."""
        return [limit for k, limit in enumerate(self.limits) if self._can_bind(k)]

    def _can_bind(self, k: int) -> bool:
        """False only when no plan could break constraint k.

        A plan has at most one line per SKU and region, so at most one line anchored on each
        (SKU, region). Its left-hand side is therefore at most the sum over anchors of their
        largest positive coefficient. A promoted-SKU cap also counts each SKU of the category
        and region at most once, so it cannot bind while it allows as many as there are such
        SKUs. These are sound but not complete: a constraint they cannot rule out is
        re-solved.
        """
        worst: dict[tuple[str, Region], int] = {}
        for line, coefficient in zip(self.lines, self.coefficients[k], strict=True):
            key = (line.sku_id, line.region)
            worst[key] = max(worst.get(key, 0), int(coefficient))
        if sum(worst.values()) <= int(self.bound[k]):
            return False
        limit = self.limits[k]
        if limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            assert limit.region is not None
            skus = {
                sku_id
                for n in self.groups[(limit.category or "", limit.region)]
                for sku_id in self.lines[n].skus
                if self.facts.sku(sku_id, limit.region).category == limit.category
            }
            return len(skus) > int(self.bound[k])
        return True

    def _named(
        self, limit: _Limit, evidence: BindingEvidence, gain: int | None
    ) -> BindingConstraint:
        rupees = None if gain is None else gain / PAISE
        rules = self.rules
        if limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            return BindingConstraint(
                kind=limit.kind,
                source=rules.max_promoted_skus_source,
                limit=rules.max_promoted_skus,
                category=limit.category,
                region=limit.region,
                evidence=evidence,
                objective_gain=rupees,
            )
        if limit.kind is ConstraintKind.MARKETING_BUDGET:
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.BRIEF,
                limit=self.request.marketing_budget,
                evidence=evidence,
                objective_gain=rupees,
            )
        if limit.kind is ConstraintKind.REGIONAL_BUDGET:
            assert limit.region is not None
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.BRIEF,
                limit=self.request.regional_budget_caps[limit.region],
                region=limit.region,
                evidence=evidence,
                objective_gain=rupees,
            )
        if limit.kind is ConstraintKind.CLEARANCE_TARGET:
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.BRIEF,
                limit=self._applied_target(limit),
                sku_id=limit.sku_id,
                region=limit.region,
                evidence=evidence,
                objective_gain=rupees,
            )
        if limit.kind is ConstraintKind.KVI_PRICE_TOLERANCE:
            assert rules.kvi_price_tolerance is not None
            return BindingConstraint(
                kind=limit.kind,
                source=rules.kvi_price_tolerance_source,
                limit=rules.kvi_price_tolerance,
                evidence=evidence,
                objective_gain=rupees,
            )
        from_brief = rules.min_margin_source is ConstraintSource.BRIEF
        return BindingConstraint(
            kind=ConstraintKind.MINIMUM_MARGIN if from_brief else ConstraintKind.MARGIN_FLOOR,
            source=rules.min_margin_source,
            limit=rules.min_margin,
            evidence=evidence,
            objective_gain=rupees,
        )

    def _applied_target(self, limit: _Limit) -> float:
        """The sell-through a clearance target holds the plan to: the brief's, or lower when
        no plan reaches it (ADR 0040)."""
        target = self.targets[limit]
        k = self.limits.index(limit)
        lowered_by = -int(self.bound[k]) - math.ceil(target.need * MILLI_UNITS - _ROUNDING)
        if lowered_by >= 0:
            return target.sell_through
        stock = target.baseline.available_stock
        return target.sell_through + lowered_by / MILLI_UNITS / stock

    def shortfalls(self, picked: list[int]) -> tuple[ClearanceShortfall, ...]:
        """Each clearance target the plan misses, on its expected units."""
        found = []
        rows = [self.eligible[n] for n in picked]
        for limit, target in self.targets.items():
            sold = target.baseline.baseline_units + sum(self._uplift(row, limit) for row in rows)
            stock = target.baseline.available_stock
            if sold / stock >= target.sell_through - _EPSILON:
                continue
            found.append(
                ClearanceShortfall(
                    sku_id=target.baseline.sku_id,
                    region=target.baseline.region,
                    target=target.sell_through,
                    expected_sell_through=sold / stock,
                    shortfall_units=target.sell_through * stock - sold,
                )
            )
        return tuple(sorted(found, key=lambda s: (s.sku_id, list(Region).index(s.region))))

    def _uplift(self, row: int, limit: _Limit) -> float:
        """The units a candidate row adds towards a clearance target over the window."""
        line = self.options.lines[row]
        if line.region is not limit.region:
            return 0.0
        numbers = self.options.table.iloc[row]
        uplift = 0.0
        if line.sku_id == limit.sku_id:
            uplift += float(numbers["window_uplift"])
        if line.bundle_partner_sku_id == limit.sku_id:
            uplift += float(numbers["partner_window_uplift"])
        return uplift

    def why_chosen(self, n: int) -> WhyChosen:
        """The positive parts of a plan line's value, the units it adds towards a clearance
        target, and whether it is the best eligible option of its SKU and region."""
        row = self.options.table.iloc[self.eligible[n]]
        towards = sum(self._uplift(self.eligible[n], limit) for limit in self.targets)
        parts = (
            (SelectionReasonCode.INCREMENTAL_PROFIT, float(row["incremental_profit"])),
            (SelectionReasonCode.CLEARANCE_VALUE, float(row["clearance_value"])),
            (SelectionReasonCode.HALO, float(row["halo_profit"])),
            (SelectionReasonCode.CLEARANCE_TARGET, towards),
        )
        line = self.lines[n]
        rivals = [
            m
            for m, other in enumerate(self.lines)
            if (other.sku_id, other.region) == (line.sku_id, line.region)
            and not self.kvi_breaking[m]
        ]
        return WhyChosen(
            reasons=tuple(
                SelectionReason(code=code, amount=amount)
                for code, amount in parts
                if round(amount * PAISE) >= 1
            ),
            value=float(row["value"]),
            best_for_sku_region=bool(self.value[n] >= self.value[rivals].max()),
        )

    def not_selected(self, picked: list[int]) -> tuple[NotSelectedOption, ...]:
        """The best option of each SKU and region with no plan line, best value first, and
        every rule it breaks alone or added to the plan."""
        plan = [self.lines[n] for n in picked]
        occupied = {(sku_id, line.region) for line in plan for sku_id in line.skus}
        values = np.rint(self.options.table["value"].to_numpy(float) * PAISE).astype(np.int64)
        best: dict[tuple[str, Region], int] = {}
        for row, line in enumerate(self.options.lines):
            if any((sku_id, line.region) in occupied for sku_id in line.skus):
                continue
            key = (line.sku_id, line.region)
            if key not in best or values[row] > values[best[key]]:
                best[key] = row
        shown = sorted(best.values(), key=lambda row: (-values[row], row))[:NOT_SELECTED_SHOWN]
        plan_rows = [self.eligible[n] for n in picked]
        terms = self._terms([(row, other) for row in shown for other in plan_rows])
        added = self.row_coefficients(shown) if shown else np.zeros((len(self.limits), 0))
        now = self.coefficients[:, picked].sum(axis=1)
        return tuple(
            self._why_not(row, int(values[row]), picked, plan_rows, terms, now + added[:, k])
            for k, row in enumerate(shown)
        )

    def _terms(self, pairs: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
        """Pairwise terms in paise for pairs of candidate rows that could run together."""
        lines = self.options.lines
        eligible = self._eligible_rows
        wanted = sorted(
            {
                _key(a, b)
                for a, b in pairs
                if _together(lines[a], lines[b])
                and _key(a, b) not in self.terms
                # Pairs of eligible options were all priced: absent means zero.
                and not (a in eligible and b in eligible)
            }
        )
        if wanted:
            computed = self.facts.pairwise_cannibalisation(
                [(lines[a], lines[b]) for a, b in wanted]
            )
            charges = np.rint(np.asarray(computed, dtype=float) * PAISE).astype(np.int64)
            self.terms.update(zip(wanted, (int(c) for c in charges), strict=True))
        return {
            key: self.terms.get(key, 0)
            for key in (_key(a, b) for a, b in pairs)
            if _together(lines[key[0]], lines[key[1]])
        }

    def _why_not(
        self,
        row: int,
        value: int,
        picked: list[int],
        plan_rows: list[int],
        terms: dict[tuple[int, int], int],
        with_it: np.ndarray,
    ) -> NotSelectedOption:
        options, table = self.options, self.options.table
        line = options.lines[row]
        reasons = set()
        if value < 1:
            reasons.add(NotSelectedReason.LOW_UPLIFT)
        number = {name: float(amount) for name, amount in table.iloc[row].items()}
        over = number["p90_units"] > number["available_stock"] + _EPSILON
        partner_over = number["partner_p90_units"] > number["partner_available_stock"] + _EPSILON
        if over or (line.bundle_partner_sku_id is not None and partner_over):
            reasons.add(NotSelectedReason.OUT_OF_STOCK)
        if not _in_window(line, self.request) or not _priced_within_policy(
            line, self.facts, self.policy, self.cleared
        ):
            reasons.add(NotSelectedReason.BREAKS_POLICY)
        for k, limit in enumerate(self.limits):
            if limit.kind in _REASONS and with_it[k] > self.bound[k]:
                reasons.add(_REASONS[limit.kind])
        if self._over_cap(line, picked):
            reasons.add(NotSelectedReason.MAX_PROMOTED_SKUS)
        losing = [
            (other, terms[_key(row, other)])
            for other in plan_rows
            if terms.get(_key(row, other), 0) > 0
        ]
        cannibalises: tuple[str, ...] = ()
        if value >= 1 and value - sum(term for _, term in losing) < 1:
            reasons.add(NotSelectedReason.CANNIBALISES)
            cannibalises = tuple(sorted({options.lines[other].sku_id for other, _ in losing}))
        if not reasons:
            # Adding it would keep every rule and gain: only a plan not proven best allows it.
            reasons.add(NotSelectedReason.TIME_LIMIT)
        order = list(NotSelectedReason)
        return NotSelectedOption(
            option=line,
            value=number["value"],
            reasons=tuple(sorted(reasons, key=order.index)),
            cannibalises=cannibalises,
        )

    def _over_cap(self, line: PlanLine, picked: list[int]) -> bool:
        chosen = set(picked)
        cap = self.rules.max_promoted_skus
        adds: defaultdict[tuple[str, Region], int] = defaultdict(int)
        for sku_id in line.skus:
            adds[(self.facts.sku(sku_id, line.region).category, line.region)] += 1
        for group, extra in adds.items():
            promoted = sum(1 for n in self.groups.get(group, []) if n in chosen)
            if promoted + extra > cap:
                return True
        return False


def _target_order(limit: _Limit) -> tuple[str, int]:
    assert limit.sku_id is not None
    assert limit.region is not None
    return (limit.sku_id, list(Region).index(limit.region))


def _eligible(
    request: PlanningRequest,
    options: PromoOptions,
    facts: OptionFacts,
    policy: CompanyPolicy,
    cleared: frozenset[str],
    targets: dict[_Limit, _Target],
) -> list[int]:
    """Options worth at least one paisa alone, or that sell more of a SKU towards a
    clearance target in its region, that keep every per-line rule, in order."""
    table = options.table
    worth = np.rint(table["value"].to_numpy(float) * PAISE) >= 1
    towards = {(limit.sku_id, limit.region) for limit in targets}
    if towards:
        anchor = table["window_uplift"].to_numpy(float) > 0
        partner = table["partner_window_uplift"].to_numpy(float) > 0
        helps = np.array(
            [
                (anchor[n] and (line.sku_id, line.region) in towards)
                or (partner[n] and (line.bundle_partner_sku_id, line.region) in towards)
                for n, line in enumerate(options.lines)
            ],
            dtype=bool,
        )
        worth = worth | helps
    fits = table["p90_units"].to_numpy(float) <= table["available_stock"].to_numpy(float) + _EPSILON
    partner_fits = (
        table["partner_p90_units"].to_numpy(float)
        <= table["partner_available_stock"].to_numpy(float) + _EPSILON
    )
    kept = []
    for n in np.flatnonzero(worth & fits):
        line = options.lines[n]
        if line.bundle_partner_sku_id is not None and not partner_fits[n]:
            continue
        if _in_window(line, request) and _priced_within_policy(line, facts, policy, cleared):
            kept.append(int(n))
    return kept


def _in_window(line: PlanLine, request: PlanningRequest) -> bool:
    window = request.promo_window
    end_week = line.start_week + line.duration_weeks - 1
    return line.start_week >= window.start_week and end_week <= window.end_week


def _priced_within_policy(
    line: PlanLine, facts: OptionFacts, policy: CompanyPolicy, cleared: frozenset[str]
) -> bool:
    """No deeper than the maximum discount, and no SKU below unit cost unless overstocked
    (by days of cover, or named for clearance)."""
    for sku_id in line.skus:
        sku = facts.sku(sku_id, line.region)
        price = effective_unit_price(line.mechanism, sku.base_price, line.depth_pct)
        if (
            sku_id == line.sku_id
            and 1 - price / sku.base_price > policy.max_discount_pct / 100 + _EPSILON
        ):
            return False
        overstocked = sku.overstocked or sku_id in cleared
        if price < sku.unit_cost - _EPSILON and not overstocked:
            return False
    return True


def _breaks_kvi(line: PlanLine, facts: OptionFacts, tolerance: float | None) -> bool:
    """Whether a KVI the line promotes stays priced more than the tolerance above the
    competitor (ADR 0031); never when the rule is off."""
    if tolerance is None:
        return False
    for sku_id in line.skus:
        sku = facts.sku(sku_id, line.region)
        if not sku.is_kvi or sku.competitor_price is None:
            continue
        price = effective_unit_price(line.mechanism, sku.base_price, line.depth_pct)
        if price > sku.competitor_price * (1 + tolerance) + _EPSILON:
            return True
    return False


def _pairs(
    lines: Sequence[PlanLine], facts: OptionFacts
) -> tuple[list[tuple[int, int]], np.ndarray]:
    """The pairs of lines that could run together with a non-zero pairwise term, in whole
    paise. Every other pair that could run together has a zero term."""
    candidates = _overlapping(lines)
    if not candidates:
        return [], np.zeros(0, dtype=np.int64)
    terms = facts.pairwise_cannibalisation([(lines[i], lines[j]) for i, j in candidates])
    charges = np.rint(np.asarray(terms, dtype=float) * PAISE).astype(np.int64)
    keep = np.flatnonzero(charges != 0)
    return [candidates[k] for k in keep], charges[keep]


def _overlapping(lines: Sequence[PlanLine]) -> list[tuple[int, int]]:
    """Pairs that could run together (`_together`), region by region, decided on arrays."""
    by_region: defaultdict[Region, list[int]] = defaultdict(list)
    for n, line in enumerate(lines):
        by_region[line.region].append(n)
    sku_codes: dict[str, int] = {}
    targets = {target: code for code, target in enumerate(TargetSegment)}
    everyone = targets[TargetSegment.ALL_CUSTOMERS]
    found: list[tuple[int, int]] = []
    for members in by_region.values():
        chosen = [lines[n] for n in members]
        start = np.array([line.start_week for line in chosen])
        end = start + np.array([line.duration_weeks for line in chosen])
        target = np.array([targets[line.target_segment] for line in chosen])
        anchor = np.array([sku_codes.setdefault(line.sku_id, len(sku_codes)) for line in chosen])
        partner = np.array(
            [
                -1
                if line.bundle_partner_sku_id is None
                else sku_codes.setdefault(line.bundle_partner_sku_id, len(sku_codes))
                for line in chosen
            ]
        )
        weeks = (start[:, None] < end[None, :]) & (start[None, :] < end[:, None])
        segments = (
            (target[:, None] == target[None, :])
            | (target[:, None] == everyone)
            | (target[None, :] == everyone)
        )
        shared = (
            (anchor[:, None] == anchor[None, :])
            | (anchor[:, None] == partner[None, :])
            | (partner[:, None] == anchor[None, :])
            | ((partner[:, None] == partner[None, :]) & (partner[:, None] >= 0))
        )
        upper = np.triu(np.ones((len(chosen), len(chosen)), dtype=bool), k=1)
        i, j = np.nonzero(weeks & segments & ~shared & upper)
        index = np.array(members)
        found += list(zip(index[i].tolist(), index[j].tolist(), strict=True))
    return found


def _together(a: PlanLine, b: PlanLine) -> bool:
    """Same region, no SKU in common, and a week and a target segment in common."""
    if a.region is not b.region or set(a.skus) & set(b.skus):
        return False
    if a.start_week + a.duration_weeks <= b.start_week:
        return False
    if b.start_week + b.duration_weeks <= a.start_week:
        return False
    everyone = TargetSegment.ALL_CUSTOMERS
    return everyone in (a.target_segment, b.target_segment) or (
        a.target_segment is b.target_segment
    )


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _paise_up(rupees: np.ndarray) -> np.ndarray:
    """Rupees in whole paise, rounded up: a constraint on them is never looser than exact."""
    return np.ceil(rupees * PAISE - _ROUNDING).astype(np.int64)


def _dot(coefficients: np.ndarray, variables: Sequence[cp_model.IntVar]) -> cp_model.LinearExpr:
    terms = [(variable, int(c)) for variable, c in zip(variables, coefficients, strict=True) if c]
    return cp_model.LinearExpr.weighted_sum([v for v, _ in terms], [c for _, c in terms])
