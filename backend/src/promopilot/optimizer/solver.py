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
  0031);
- no two strong substitutes promoted together (ADR 0075): SKUs the relations model detects as
  substitutes with an estimated θ at least company policy's `strong_substitute_min_theta` are
  never in plan lines that run together, in one region with a promo week and a target segment
  in common, a BUNDLE's partner included. For each such pair, region, week and segment, at
  most one option that covers that cell is selected; options of one SKU and region already
  exclude each other, so this is exact.

A brief may only tighten company policy; `plan_limits` applies it and reports what it did not
apply (ADR 0007). Only options worth at least one paisa alone are eligible, or that sell more
of a SKU towards its clearance target, so every plan line pays for itself, is a clearance SKU
whose clearance value justifies it (F-01 AC1), or is needed for a clearance target the brief
set. An eligible option must also keep every per-line rule: P90 units within available stock
(a BUNDLE's partner too, ADR 0004), inside the promo window, no deeper than the maximum
discount and not below unit cost unless overstocked (ADR 0007), and not a BUNDLE of two
strong substitutes; a SKU named for clearance is overstocked. Costs are rounded up and the
budgets down to whole paise, and units sold towards a target down, so every plan the solver
accepts also passes `validate_plan` (ADR 0012).

With clearance targets the solve has two phases (ADR 0040). The first finds the plan closest to
every target, the least stock left short of target weighted by unit cost, under every other
constraint. Each target is then lowered to what that plan reaches, and the second phase
maximises the objective. When every target is reachable this is exactly the hard model; when
one is not, the plan comes as close as any can and `clearance_shortfalls` reports by how much
it falls short. The empty plan is always feasible in the first phase, so there is always a
plan to return, even when no better one is found in time. When the first phase runs out of
work short of a target, a check with every target hard and no objective settles whether any
plan reaches them all, on up to half the relaxation budget (ADR 0074): proving that none does
is quick where proving the least shortfall is not. A plan it finds keeps the brief's targets
for the second phase. Without targets, a solve that finds nothing but the empty plan in time
returns the greedy plan instead: best value first, each option kept when it keeps every
constraint and gains net of its pairwise terms (ADR 0074).

A request is infeasible exactly when no plan reaches every clearance target within its other
constraints: every other constraint is one the empty plan keeps (ADR 0044). A plan that misses
a target is INFEASIBLE, never FEASIBLE (ADR 0074): proven when the first phase or the check
proves no plan reaches every target, and otherwise with a relaxation that says it is not
proven. The closest plan still comes back, and so does the relaxation: the smallest change to
the brief's own constraints (budget, regional caps, minimum margin down to the floor, a
tighter promoted-SKU cap, a KVI tolerance the brief turned on, the clearance targets) that
makes it feasible, each change weighed in basis points of the brief's value. Company policy,
the strong-substitute rule included, is never relaxed; when only lowering a target helps,
policy binds.

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
interleaves their search. Every phase stops on CP-SAT's deterministic time, a measure of work
done rather than of seconds passed, so the same input gives the same plan, status, binding
constraints and relaxation on any machine, however fast or busy (ADR 0055). Wall-clock limits
remain only as safety nets that a healthy machine never reaches.
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
    Relaxation,
    RelaxedConstraint,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    TargetSegment,
    WhyChosen,
)
from promopilot.economics import effective_unit_price
from promopilot.guardrails import (
    PlanLimits,
    SkuFacts,
    SubstituteFacts,
    plan_limits,
    run_together,
)
from promopilot.optimizer.options import ClearanceBaseline, PromoOptions

PAISE = 100
MILLI_UNITS = 1000
"""Clearance constraints count units in thousandths: CP-SAT needs whole numbers."""
_EPSILON = 1e-9
_ROUNDING = 1e-6
"""Paise (or thousandths of a unit) lost to float noise before rounding up or down."""
_MIN_RESOLVE_SECONDS = 0.001
"""Less binding time left than this, of work or of its wall-clock net, settles no more
constraints."""
BASIS_POINTS = 10_000
"""A relaxation's changes are weighed in basis points of the brief's own values (ADR 0044),
and relaxed margins and sell-throughs are reported to a basis point."""
MARGIN_STEP = 0.005
"""The steps by which the relaxation may lower the brief's minimum margin; the relaxed margin
reported is the plan's own, to a basis point."""


@dataclass(frozen=True)
class SolverSettings:
    """How much work each phase may do, in CP-SAT deterministic seconds, and the wall-clock
    net behind it (ADR 0055):

    - a solve: OPTIMIZER_DETERMINISTIC_LIMIT and OPTIMIZER_TIME_LIMIT_SECONDS;
    - the re-solves that find binding constraints, shared: OPTIMIZER_BINDING_DETERMINISTIC_LIMIT
      and OPTIMIZER_BINDING_TIME_LIMIT_SECONDS (ADR 0038);
    - the smallest relaxation of an infeasible request: OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT
      and OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS (ADR 0044), up to half of each first spent
      checking whether any plan reaches every clearance target when the closest-plan search
      runs out of work (ADR 0074);

    and the worker count (OPTIMIZER_WORKERS). The work budgets decide the result. A wall-clock
    net that runs out first ends the phase too, but then not the same way on every machine. A
    binding budget or net of 0 turns the binding analysis off."""

    time_limit_seconds: float = 60.0
    workers: int = 1
    binding_time_limit_seconds: float = 30.0
    relaxation_time_limit_seconds: float = 60.0
    deterministic_limit: float = 10.0
    binding_deterministic_limit: float = 6.0
    relaxation_deterministic_limit: float = 10.0

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("the solver's time limit must be positive")
        if self.workers < 1:
            raise ValueError("the solver needs at least one worker")
        if self.binding_time_limit_seconds < 0:
            raise ValueError("the binding time limit cannot be negative")
        if self.relaxation_time_limit_seconds <= 0:
            raise ValueError("the relaxation time limit must be positive")
        if self.deterministic_limit <= 0:
            raise ValueError("the solver's deterministic limit must be positive")
        if self.binding_deterministic_limit < 0:
            raise ValueError("the binding deterministic limit cannot be negative")
        if self.relaxation_deterministic_limit <= 0:
            raise ValueError("the relaxation deterministic limit must be positive")


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

    def substitutes(self, sku_ids: Sequence[str]) -> Sequence[SubstituteFacts]:
        """The detected substitute pairs among these SKUs, each once, with the relations
        model's estimated θ (ADR 0075)."""
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
    relaxation: Relaxation | None = None
    """When no plan is found that reaches every clearance target, the smallest change to the
    brief's constraints that would make the request feasible (ADR 0044)."""


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
    brief = problem  # with the brief's own clearance targets, before any is lowered
    findings = problem.rules.findings
    closest: _Closest | None = None
    infeasible = False  # proven that no plan reaches every clearance target
    time_limit, work = settings.time_limit_seconds, settings.deterministic_limit
    relax_limit = settings.relaxation_time_limit_seconds
    relax_work = settings.relaxation_deterministic_limit
    if problem.targets:
        # The closest plan takes up to half of each; the main solve what it left (ADR 0055).
        closest = problem.closest(settings, seed, time_limit=time_limit / 2, work=work / 2)
        time_limit = max(time_limit - (time.monotonic() - started), time_limit / 2)
        work = max(work - closest.work, work / 2)
        infeasible = closest.proven
        if any(closest.shortfall.values()) and not closest.proven:
            # The closest search ran out of work short of a target: settle whether any plan
            # reaches every target, on up to half the relaxation budget (ADR 0074).
            checked = time.monotonic()
            check = problem.reach(
                settings, seed, hint=closest.picked, time_limit=relax_limit / 2, work=relax_work / 2
            )
            relax_limit = max(relax_limit - (time.monotonic() - checked), relax_limit / 2)
            relax_work = max(relax_work - check.work, relax_work / 2)
            infeasible = check.status == cp_model.INFEASIBLE
            if check.status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                reached = dict.fromkeys(closest.shortfall, 0)
                closest = _Closest(check.picked, reached, True, closest.work)
        problem = problem.lowered(closest.shortfall)
    outcome = problem.solve(
        settings, seed, hint=closest.picked if closest else (), time_limit=time_limit, work=work
    )
    found = outcome.status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    picked, charged = (outcome.picked, outcome.charged) if found else ([], 0)
    if closest is not None and not found:
        # No plan found in time: the closest plan keeps every constraint, the lowered targets
        # included.
        picked, charged = closest.picked, problem.charged(closest.picked)
    elif closest is None and outcome.status != cp_model.OPTIMAL and not picked:
        # Nothing but the empty plan found in time: the greedy plan keeps every constraint
        # too, and is never worse (ADR 0074).
        picked = problem.greedy()
        charged = problem.charged(picked)
    objective = int(problem.value[picked].sum()) - charged
    shortfalls = problem.shortfalls(picked)
    relaxation: Relaxation | None = None
    binding: tuple[BindingConstraint, ...]
    if closest is not None and any(closest.shortfall.values()):
        # No plan found reaches every clearance target (ADR 0044): the brief's own constraints
        # say what must give. A plan that misses a target is never FEASIBLE; when no plan
        # reaching it is not proven impossible, the relaxation is not proven (ADR 0074).
        relaxation, relaxed_plan = brief.relax(
            closest, settings, seed, proven=infeasible, time_limit=relax_limit, work=relax_work
        )
        status = SolveStatus.INFEASIBLE
        binding = brief.infeasible(relaxation, relaxed_plan, shortfalls)
    elif outcome.status == cp_model.OPTIMAL and (closest is None or closest.proven):
        status = SolveStatus.OPTIMAL
        binding = problem.binding(picked, objective, settings, seed)
    else:
        status = SolveStatus.FEASIBLE
        binding = problem.unproven()
    return OptimisationResult(
        status=status,
        objective=objective / PAISE,
        plan=PromoPlan(lines=tuple(problem.lines[n] for n in picked)),
        selected=tuple(problem.eligible[n] for n in picked),
        pairwise_cannibalisation=charged / PAISE,
        eligible=problem.choosable,
        pairs=len(problem.pairs) if found or closest or picked else 0,
        binding_constraints=binding,
        why_chosen=tuple(problem.why_chosen(n) for n in picked),
        not_selected=problem.not_selected(picked),
        clearance_shortfalls=shortfalls,
        policy_findings=findings,
        relaxation=relaxation,
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
_GUARD = _Limit(ConstraintKind.STRONG_SUBSTITUTES)
"""The strong-substitute rule: not a row of `coefficients` but at-most-one groups
(`_Problem.guard`), so it has no index in `_Problem.limits`."""

_REASONS = {
    ConstraintKind.MARKETING_BUDGET: NotSelectedReason.OVER_BUDGET,
    ConstraintKind.REGIONAL_BUDGET: NotSelectedReason.OVER_REGIONAL_BUDGET,
    ConstraintKind.MINIMUM_MARGIN: NotSelectedReason.BREAKS_MARGIN,
    ConstraintKind.CLEARANCE_TARGET: NotSelectedReason.MISSES_CLEARANCE_TARGET,
    ConstraintKind.KVI_PRICE_TOLERANCE: NotSelectedReason.BREAKS_KVI_TOLERANCE,
}
"""The not-selected reason for adding an option that breaks a constraint (the promoted-SKU
cap has its own check, `_over_cap`, and the strong-substitute rule `_strong_partners`)."""


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
    work: float = 0.0
    """The deterministic time the solve took."""


@dataclass(frozen=True)
class _Closest:
    """The first phase with clearance targets: the plan closest to every target."""

    picked: list[int]
    shortfall: dict[_Limit, int]
    """Thousandths of a unit short of each target."""
    proven: bool
    """Whether no plan is proven closer."""
    work: float = 0.0
    """The deterministic time the search took."""


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
    conflict: np.ndarray
    """options x plan lines: the option and the plan line may not run together under the
    strong-substitute rule."""


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
    strong: dict[frozenset[str], float]
    """The strong substitute pairs among the options' SKUs, with their estimated θ."""
    guard: list[tuple[int, ...]]
    """Groups of eligible options of which at most one may be selected: those covering one
    week and segment in one region with either SKU of a strong pair (ADR 0075)."""
    _keys: list[list[tuple[str, Region]]] = field(default_factory=list, init=False)
    """The (SKU, region)s each eligible option occupies."""
    _near: list[dict[int, int]] = field(default_factory=list, init=False)
    """Each eligible option's non-zero pairwise terms, by the other option."""
    _swap_cache: dict[tuple[int, ...], "_Swaps | None"] = field(default_factory=dict, init=False)
    _eligible_rows: set[int] = field(default_factory=set, init=False)
    _conflicts: list[set[int]] = field(default_factory=list, init=False)
    """Each eligible option's options it may not run with under the strong-substitute rule."""

    def __post_init__(self) -> None:
        self._eligible_rows = set(self.eligible)
        self._conflicts = [set() for _ in self.lines]
        for group in self.guard:
            for n in group:
                self._conflicts[n].update(m for m in group if m != n)
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
        strong = _strong_pairs(options.lines, facts, policy)
        eligible = _eligible(request, options, facts, policy, cleared, targets, strong)
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
            strong=strong,
            guard=_guard_groups(lines, strong),
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

    def closest(
        self, settings: SolverSettings, seed: int, *, time_limit: float, work: float
    ) -> _Closest:
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
        solver = self._solver(settings, seed, time_limit, work, first=False)
        status = solver.solve(model)
        found = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        picked = [n for n, chosen in enumerate(x) if found and solver.boolean_value(chosen)]
        shortfall = {
            limit: max(0, int(self.coefficients[k, picked].sum()) - int(self.bound[k]))
            for k, limit in enumerate(self.limits)
            if limit in self.targets
        }
        return _Closest(picked, shortfall, status == cp_model.OPTIMAL, solver.deterministic_time)

    def reach(
        self,
        settings: SolverSettings,
        seed: int,
        *,
        hint: Sequence[int],
        time_limit: float,
        work: float,
    ) -> _Outcome:
        """The first plan found that keeps every constraint, each clearance target at its
        bound, or proof (INFEASIBLE) that none does (ADR 0074). No objective: proving that
        some target must be missed is quick where proving the least shortfall is not."""
        model = cp_model.CpModel()
        x = self._variables(model)
        for k in range(len(self.limits)):
            model.add(_dot(self.coefficients[k], x) <= int(self.bound[k]))
        hinted = set(hint)
        for n, chosen in enumerate(x):
            model.add_hint(chosen, n in hinted)
        solver = self._solver(settings, seed, time_limit, work, first=True)
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _Outcome(status, [], 0, solver.deterministic_time)
        picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
        return _Outcome(status, picked, self.charged(picked), solver.deterministic_time)

    def greedy(self) -> list[int]:
        """A plan built best value first (ADR 0074): each option joins when it keeps every
        constraint and one line per SKU and region, and gains at least a paisa net of its
        pairwise terms with the lines already in. No solver and no clock, so the same input
        gives the same plan; ties go to the earlier option. Empty when the model holds a
        constraint the empty plan breaks (a clearance target)."""
        picked: list[int] = []
        taken: set[tuple[str, Region]] = set()
        totals = np.zeros(len(self.limits), dtype=np.int64)
        for n in np.argsort(-self.value, kind="stable").tolist():
            if any(key in taken for key in self._keys[n]):
                continue
            after = totals + self.coefficients[:, n]
            if (after > self.bound).any():
                continue
            if int(self.value[n]) - sum(self._near[n].get(m, 0) for m in picked) < 1:
                continue
            picked.append(n)
            taken.update(self._keys[n])
            totals = after
        return sorted(picked)

    def solve(
        self,
        settings: SolverSettings,
        seed: int,
        *,
        drop: _Limit | None = None,
        hint: Sequence[int] = (),
        beat: int | None = None,
        time_limit: float | None = None,
        work: float | None = None,
        first: bool = False,
        breaking: bool = False,
    ) -> _Outcome:
        """Solve the model, without the `drop` constraint, starting from the `hint` plan,
        within `work` deterministic seconds and a `time_limit` net (those of `settings` by
        default). With `beat`,
        only plans whose objective (paise) is at least that are feasible. With `breaking`,
        only plans that break the `drop` constraint are. With `first`, the search stops at
        the first feasible plan."""
        model = cp_model.CpModel()
        x = self._variables(model, guard=drop != _GUARD)
        if drop == _GUARD and breaking:
            broken = []
            for n, group in enumerate(self.guard):
                both = model.new_bool_var(f"g{n}")
                model.add(sum(x[m] for m in group) >= 2).only_enforce_if(both)
                broken.append(both)
            model.add_bool_or(broken)
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

        solver = self._solver(
            settings,
            seed,
            time_limit or settings.time_limit_seconds,
            work or settings.deterministic_limit,
            first,
        )
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _Outcome(status, [], 0, solver.deterministic_time)
        picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
        charged = int(
            sum(c for c, both in zip(self.charges, y, strict=True) if solver.boolean_value(both))
        )
        return _Outcome(status, picked, charged, solver.deterministic_time)

    def _variables(self, model: cp_model.CpModel, *, guard: bool = True) -> list[cp_model.IntVar]:
        """One x per eligible option, at most one per (SKU, region) it occupies and, with
        `guard`, at most one per strong-substitute group (ADR 0075)."""
        x = [model.new_bool_var(f"x{n}") for n in range(len(self.lines))]
        occupied: defaultdict[tuple[str, Region], list[cp_model.IntVar]] = defaultdict(list)
        for chosen, keys in zip(x, self._keys, strict=True):
            for key in keys:
                occupied[key].append(chosen)
        for variables in occupied.values():
            model.add_at_most_one(variables)
        if guard:
            for group in self.guard:
                model.add_at_most_one([x[n] for n in group])
        return x

    @staticmethod
    def _solver(
        settings: SolverSettings, seed: int, time_limit: float, work: float, first: bool
    ) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = seed
        solver.parameters.num_workers = settings.workers
        solver.parameters.interleave_search = settings.workers > 1
        # The work budget decides where the search ends, on any machine; the wall-clock
        # limit is a safety net (ADR 0055).
        solver.parameters.max_deterministic_time = work
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
        what is left of the binding budget, in deterministic seconds (and of its wall-clock
        net), and any work left after that is spent on making the lower bounds exact. The
        pairwise terms are the ones already priced. Whatever is still unsettled at the end is
        unproven. The budget shrinks by the work each re-solve did, so which constraints are
        settled does not depend on the machine (ADR 0055).
        """
        limits = self._limits()
        deadline = time.monotonic() + settings.binding_time_limit_seconds
        budget = [settings.binding_deterministic_limit]
        settled: dict[_Limit, tuple[BindingEvidence, int, list[int]] | None] = {}

        def left() -> float:
            return deadline - time.monotonic()

        def spent() -> bool:
            return budget[0] < _MIN_RESOLVE_SECONDS or left() < _MIN_RESOLVE_SECONDS

        for limit in limits:
            if spent():
                break
            swapped = self._swap(picked, limit)
            if swapped is not None:
                reached, better = swapped
                settled[limit] = (BindingEvidence.LOWER_BOUND, reached - objective, better)

        open_ = [limit for limit in limits if limit not in settled]
        for k, limit in enumerate(open_):
            if spent():
                break
            relaxed = self.solve(
                settings,
                seed,
                drop=limit,
                hint=picked,
                beat=objective + 1,
                time_limit=min(left() / (len(open_) - k), settings.time_limit_seconds),
                work=min(budget[0] / (len(open_) - k), settings.deterministic_limit),
                first=True,
                breaking=True,
            )
            budget[0] -= relaxed.work
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
            if spent():
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
                work=min(budget[0] / (len(bounded) - k), settings.deterministic_limit),
            )
            budget[0] -= relaxed.work
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
        if drop != _GUARD:
            # The swap keeps the strong-substitute rule when every plan line the option may
            # not run with is taken out: a clash, or the one extra line.
            left = swaps.conflict & ~swaps.clash
            count = left.sum(axis=1)
            keeps = np.concatenate([(count[:, None] - left) == 0, (count == 0)[:, None]], axis=1)
            valid &= keeps
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
        conflict = np.zeros((size, count), dtype=bool)
        for o in range(size):
            for n in self._conflicts[o]:
                if n in position:
                    conflict[o, position[n]] = True
        swaps = _Swaps(
            plan=picked, clash=clash, gain=gain, after=after, valid=valid, conflict=conflict
        )
        self._swap_cache[key] = swaps
        return swaps

    def _evaluate(self, plan: list[int], drop: _Limit) -> int | None:
        """The plan's objective in paise if it keeps every constraint but `drop`."""
        keys = [key for n in plan for key in self._keys[n]]
        if len(keys) != len(set(keys)):
            return None
        chosen = set(plan)
        if drop != _GUARD and any(self._conflicts[n] & chosen for n in plan):
            return None
        totals = self.coefficients[:, plan].sum(axis=1)
        for k, limit in enumerate(self.limits):
            if limit != drop and totals[k] > self.bound[k]:
                return None
        return int(self.value[plan].sum()) - self.charged(plan)

    def _objective(self, outcome: _Outcome) -> int:
        return int(self.value[outcome.picked].sum()) - outcome.charged

    def _limits(self) -> list[_Limit]:
        """The constraints that some plan could break (`_can_bind`), and the strong-substitute
        rule when two options could run together against it."""
        found = [limit for k, limit in enumerate(self.limits) if self._can_bind(k)]
        return found + ([_GUARD] if self.guard else [])

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
        if limit == _GUARD:
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.COMPANY_POLICY,
                limit=self.policy.strong_substitute_min_theta,
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

    def relax(
        self,
        closest: _Closest,
        settings: SolverSettings,
        seed: int,
        *,
        proven: bool,
        time_limit: float,
        work: float,
    ) -> tuple[Relaxation, list[int]]:
        """The smallest change to the brief's constraints that makes every clearance target
        reachable (ADR 0044), and a plan that reaches them with it. `proven` says whether the
        request is proven infeasible; only then can the relaxation be proven (ADR 0074).

        Two re-solves share what is left of the relaxation budget: `work` deterministic
        seconds within a `time_limit` net (ADR 0055, ADR 0074). The
        first frees every brief constraint but the clearance targets as far as company policy
        allows: if a target must still come down, policy binds. The second finds the least sum
        of changes, each in basis points of the brief's value. When it finds nothing within its
        budget, the closest plan gives the relaxation: each target lowered to what it reaches.
        """
        started = time.monotonic()
        limit = time_limit
        held = self._least_change(
            settings, seed, closest.picked, free=True, time_limit=limit / 2, work=work / 2
        )
        left = max(limit - (time.monotonic() - started), limit / 2)
        whole = self._least_change(
            settings,
            seed,
            closest.picked,
            free=False,
            time_limit=left,
            work=max(work - held.work, work / 2),
        )
        found = (cp_model.OPTIMAL, cp_model.FEASIBLE)
        plan = whole.picked if whole.status in found else closest.picked
        policy_binds = held.status in found and held.cost > 0
        allows = (
            {
                change.sku_id: change.relaxed or 0.0
                for change in self._changes(held.picked)
                if change.kind is ConstraintKind.CLEARANCE_TARGET
            }
            if policy_binds
            else {}
        )
        changes = tuple(
            change.model_copy(update={"policy_allows": allows[change.sku_id]})
            if change.sku_id in allows
            else change
            for change in self._changes(plan)
        )
        proven = proven and held.status == whole.status == cp_model.OPTIMAL
        return Relaxation(changes=changes, policy_binds=policy_binds, proven=proven), plan

    def _least_change(
        self,
        settings: SolverSettings,
        seed: int,
        hint: Sequence[int],
        *,
        free: bool,
        time_limit: float,
        work: float,
    ) -> "_Change":
        """A plan that reaches every clearance target with the least change to the brief's
        constraints, each in basis points of the brief's value. With `free`, every brief
        constraint but the targets is relaxed as far as policy allows at no cost, so only
        lowering a target counts. Company policy is never relaxed."""
        model = cp_model.CpModel()
        x = self._variables(model)
        rules, policy = self.rules, self.policy
        costs: list[tuple[int, cp_model.IntVar]] = []

        def slack(upper: int, name: str, weight: int) -> cp_model.IntVar:
            variable = model.new_int_var(0, upper, name)
            if free:
                model.add(variable == upper)
            else:
                costs.append((weight, variable))
            return variable

        room = policy.max_promoted_skus_per_category_per_region - rules.max_promoted_skus
        extra_skus = None
        if rules.max_promoted_skus_source is ConstraintSource.BRIEF and room > 0:
            weight = math.ceil(BASIS_POINTS / rules.max_promoted_skus)
            extra_skus = slack(room, "cap", weight)
        lowered: dict[str, tuple[cp_model.IntVar, cp_model.IntVar]] = {}
        for sku_id in sorted({str(limit.sku_id) for limit in self.targets}):
            by = model.new_int_var(0, BASIS_POINTS - 1, f"lower_{sku_id}")
            dropped = model.new_bool_var(f"drop_{sku_id}")
            costs += [(1, by), (BASIS_POINTS, dropped)]
            lowered[sku_id] = (by, dropped)
        tolerance = policy.kvi_price_tolerance if policy.kvi_price_tolerance_enabled else None
        for k, limit in enumerate(self.limits):
            expression = _dot(self.coefficients[k], x)
            bound = int(self.bound[k])
            if limit == _BUDGET or limit.kind is ConstraintKind.REGIONAL_BUDGET:
                most = int(np.maximum(self.coefficients[k], 0).sum())
                base = max(bound, 1)
                upper = max(0, math.ceil(BASIS_POINTS * (most - bound) / base))
                more = slack(upper, f"more{k}", 1)
                model.add(BASIS_POINTS * expression - base * more <= BASIS_POINTS * bound)
            elif limit == _MARGIN and rules.min_margin_source is ConstraintSource.BRIEF:
                self._margin_levels(model, x, free, costs)
            elif limit.kind is ConstraintKind.MAX_PROMOTED_SKUS and extra_skus is not None:
                model.add(expression - extra_skus <= bound)
            elif limit in self.targets:
                target = self.targets[limit]
                by, dropped = lowered[str(limit.sku_id)]
                units = target.sell_through * target.baseline.available_stock
                per = math.floor(units * MILLI_UNITS + _ROUNDING)
                model.add(
                    BASIS_POINTS * expression - per * by <= BASIS_POINTS * bound
                ).only_enforce_if(dropped.Not())
            elif limit == _KVI and rules.kvi_price_tolerance_source is ConstraintSource.BRIEF:
                off = slack(1, "kvi_off", BASIS_POINTS)
                model.add(expression <= 0).only_enforce_if(off.Not())
                if tolerance is not None:
                    breaking = [_breaks_kvi(line, self.facts, tolerance) for line in self.lines]
                    model.add(_dot(np.array(breaking, dtype=np.int64), x) <= 0)
            else:
                model.add(expression <= bound)
        model.minimize(sum(weight * variable for weight, variable in costs))
        hinted = set(hint)
        for n, chosen in enumerate(x):
            model.add_hint(chosen, n in hinted)
        solver = self._solver(settings, seed, time_limit, work, first=False)
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _Change(status, [], 0, solver.deterministic_time)
        picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
        return _Change(status, picked, round(solver.objective_value), solver.deterministic_time)

    def _margin_levels(
        self,
        model: cp_model.CpModel,
        x: list[cp_model.IntVar],
        free: bool,
        costs: list[tuple[int, cp_model.IntVar]],
    ) -> None:
        """The brief's minimum margin, which may come down in MARGIN_STEP steps to the
        company-policy margin floor, each level costing its change in basis points."""
        minimum, floor = self.rules.min_margin, self.policy.margin_floor
        levels = [floor]
        if not free:
            steps = math.ceil((minimum - floor) / MARGIN_STEP - _ROUNDING)
            levels = [minimum - step * MARGIN_STEP for step in range(steps)] + [floor]
        table = self.options.table.iloc[self.eligible]
        revenue = table["revenue"].to_numpy(float)
        gross_profit = table["gross_profit"].to_numpy(float)
        chosen = []
        for n, level in enumerate(levels):
            at = model.new_bool_var(f"margin{n}")
            short = _paise_up(level * revenue - gross_profit)
            model.add(_dot(short, x) <= 0).only_enforce_if(at)
            chosen.append(at)
            weight = math.ceil(BASIS_POINTS * (minimum - level) / minimum - _ROUNDING)
            if weight > 0 and not free:
                costs.append((weight, at))
        model.add_exactly_one(chosen)

    def _changes(self, plan: list[int]) -> list[RelaxedConstraint]:
        """The smallest change to each brief constraint the plan breaks that lets it keep
        them: a budget to what it spends, the minimum margin to the plan's blended margin (to
        a basis point), the promoted-SKU cap to the most it promotes, the KVI tolerance to
        policy's, and each clearance target to the least any region reaches (to a basis
        point), or dropped."""
        totals = self.coefficients[:, plan].sum(axis=1)
        rules, request = self.rules, self.request
        over = [
            (limit, int(total))
            for limit, total, bound in zip(self.limits, totals, self.bound, strict=True)
            if int(total) > int(bound)
        ]
        found: list[RelaxedConstraint] = []
        for limit, total in over:
            if limit == _BUDGET:
                found.append(_raised(limit.kind, request.marketing_budget, total / PAISE))
        for limit, total in over:
            if limit.kind is ConstraintKind.REGIONAL_BUDGET:
                assert limit.region is not None
                cap = request.regional_budget_caps[limit.region]
                found.append(_raised(limit.kind, cap, total / PAISE, region=limit.region))
        if any(limit == _MARGIN for limit, _ in over):
            margin = self._least_margin(plan)
            found.append(
                RelaxedConstraint(
                    kind=ConstraintKind.MINIMUM_MARGIN,
                    current=rules.min_margin,
                    relaxed=margin,
                    change=(rules.min_margin - margin) / rules.min_margin,
                )
            )
        most = max(
            (total for limit, total in over if limit.kind is ConstraintKind.MAX_PROMOTED_SKUS),
            default=0,
        )
        if most:
            found.append(_raised(ConstraintKind.MAX_PROMOTED_SKUS, rules.max_promoted_skus, most))
        if any(limit == _KVI for limit, _ in over):
            assert rules.kvi_price_tolerance is not None
            enabled = self.policy.kvi_price_tolerance_enabled
            found.append(
                RelaxedConstraint(
                    kind=ConstraintKind.KVI_PRICE_TOLERANCE,
                    current=rules.kvi_price_tolerance,
                    relaxed=self.policy.kvi_price_tolerance if enabled else None,
                    change=1.0,
                )
            )
        reached: dict[str, float | None] = {}
        for limit, total in over:
            if limit in self.targets:
                sku_id = str(limit.sku_id)
                share = self._reachable(limit, total)
                earlier = reached.get(sku_id, 1.0)
                reached[sku_id] = None if share is None or earlier is None else min(share, earlier)
        wanted = {target.sku_id: target.sell_through for target in request.clearance_targets}
        for sku_id, share in sorted(reached.items()):
            asked = wanted[sku_id]
            found.append(
                RelaxedConstraint(
                    kind=ConstraintKind.CLEARANCE_TARGET,
                    sku_id=sku_id,
                    current=asked,
                    relaxed=share,
                    change=1.0 if share is None else (asked - share) / asked,
                )
            )
        return found

    def _least_margin(self, plan: list[int]) -> float:
        """The highest minimum margin, to a basis point and never below the margin floor,
        that the plan keeps with its margin shortfalls rounded as the solver rounds them."""
        table = self.options.table.iloc[[self.eligible[n] for n in plan]]
        revenue = table["revenue"].to_numpy(float)
        gross_profit = table["gross_profit"].to_numpy(float)
        floor = self.policy.margin_floor
        blended = gross_profit.sum() / revenue.sum() if revenue.sum() > 0 else floor
        level = math.floor(min(blended, self.rules.min_margin) * BASIS_POINTS + _ROUNDING)
        while (
            level / BASIS_POINTS > floor
            and _paise_up(level / BASIS_POINTS * revenue - gross_profit).sum() > 0
        ):
            level -= 1
        return max(level / BASIS_POINTS, floor)

    def _reachable(self, limit: _Limit, total: int) -> float | None:
        """The highest sell-through, to a basis point, that the plan reaches for a clearance
        target in its region, with units rounded as the solver rounds them; None below one
        basis point."""
        baseline = self.targets[limit].baseline
        sold = -total  # thousandths of a unit the plan adds over the window
        stock, base = baseline.available_stock, baseline.baseline_units
        share = math.floor((base + sold / MILLI_UNITS) / stock * BASIS_POINTS + _ROUNDING)
        while (
            share > 0
            and math.ceil((share / BASIS_POINTS * stock - base) * MILLI_UNITS - _ROUNDING) > sold
        ):
            share -= 1
        return share / BASIS_POINTS if share > 0 else None

    def infeasible(
        self,
        relaxation: Relaxation,
        relaxed_plan: list[int],
        shortfalls: Sequence[ClearanceShortfall],
    ) -> tuple[BindingConstraint, ...]:
        """The binding constraints of an infeasible request: each clearance target the plan
        misses and each constraint the relaxation changes, at the brief's values."""
        kinds = {change.kind for change in relaxation.changes}
        regions = {
            change.region
            for change in relaxation.changes
            if change.kind is ConstraintKind.REGIONAL_BUDGET
        }
        missed = {(shortfall.sku_id, shortfall.region) for shortfall in shortfalls}
        totals = self.coefficients[:, relaxed_plan].sum(axis=1)
        found = []
        for k, limit in enumerate(self.limits):
            if limit.kind is ConstraintKind.CLEARANCE_TARGET:
                binds = (limit.sku_id, limit.region) in missed
            elif limit.kind is ConstraintKind.REGIONAL_BUDGET:
                binds = limit.region in regions
            elif limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
                binds = limit.kind in kinds and int(totals[k]) > int(self.bound[k])
            elif limit == _MARGIN:
                binds = ConstraintKind.MINIMUM_MARGIN in kinds
            else:
                binds = limit.kind in kinds
            if binds:
                found.append(self._named(limit, BindingEvidence.INFEASIBLE, None))
        return tuple(found)

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
        named: set[str] = set()
        if value >= 1 and value - sum(term for _, term in losing) < 1:
            reasons.add(NotSelectedReason.CANNIBALISES)
            named |= {options.lines[other].sku_id for other, _ in losing}
        partners = self._strong_partners(line, [options.lines[other] for other in plan_rows])
        if partners is not None:
            reasons.add(NotSelectedReason.STRONG_SUBSTITUTE)
            named |= partners
        cannibalises = tuple(sorted(named))
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

    def _strong_partners(self, line: PlanLine, plan: Sequence[PlanLine]) -> set[str] | None:
        """The plan's SKUs the line would promote a strong substitute of together with (its
        own, for a BUNDLE of a strong pair); None if it keeps the rule (ADR 0075)."""
        found: set[str] = set()
        breaks = _has_strong_pair(line.skus, self.strong)
        for other in plan:
            if not run_together(line, other):
                continue
            for sku_id in line.skus:
                for other_sku_id in other.skus:
                    if frozenset((sku_id, other_sku_id)) in self.strong:
                        breaks = True
                        found.add(other_sku_id)
        if breaks and not found:
            found = set(line.skus)
        return found if breaks else None

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


@dataclass(frozen=True)
class _Change:
    """A plan found with the least change to the brief's constraints."""

    status: cp_model.CpSolverStatus
    picked: list[int]
    cost: int
    """The sum of its changes in basis points of the brief's values."""
    work: float = 0.0
    """The deterministic time the search took."""


def _raised(
    kind: ConstraintKind, current: float, needed: float, *, region: Region | None = None
) -> RelaxedConstraint:
    return RelaxedConstraint(
        kind=kind,
        region=region,
        current=current,
        relaxed=float(needed),
        change=(needed - current) / current,
    )


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
    strong: dict[frozenset[str], float],
) -> list[int]:
    """Options worth at least one paisa alone, or that sell more of a SKU towards a
    clearance target in its region, that keep every per-line rule, in order: a BUNDLE of two
    strong substitutes promotes them together, so it is not eligible (ADR 0075)."""
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
        if _has_strong_pair(line.skus, strong):
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
    return not set(a.skus) & set(b.skus) and run_together(a, b)


def _strong_pairs(
    lines: Sequence[PlanLine], facts: OptionFacts, policy: CompanyPolicy
) -> dict[frozenset[str], float]:
    """The pairs of the options' SKUs the relations model detects as substitutes with an
    estimated θ of at least the policy's strong-substitute minimum (ADR 0075)."""
    sku_ids = sorted({sku_id for line in lines for sku_id in line.skus})
    least = policy.strong_substitute_min_theta
    return {
        frozenset((pair.sku_id, pair.other_sku_id)): pair.theta
        for pair in facts.substitutes(sku_ids)
        if pair.sku_id != pair.other_sku_id and pair.theta >= least - _EPSILON
    }


def _has_strong_pair(sku_ids: Sequence[str], strong: dict[frozenset[str], float]) -> bool:
    return any(frozenset((a, b)) in strong for n, a in enumerate(sku_ids) for b in sku_ids[n + 1 :])


_SEGMENTS = [target for target in TargetSegment if target is not TargetSegment.ALL_CUSTOMERS]


def _guard_groups(
    lines: Sequence[PlanLine], strong: dict[frozenset[str], float]
) -> list[tuple[int, ...]]:
    """For each strong pair, region, week and segment, the options that cover that cell with
    either SKU, where both SKUs have one: at most one of them may be selected (ADR 0075).

    Two lines run together exactly when they cover a common cell, All customers covering
    every segment. Options of one SKU in one region already exclude each other, so at most
    one per group forbids exactly the pairs that run together. Groups come sorted, each once.
    """
    if not strong:
        return []
    by_key: defaultdict[tuple[str, Region], list[int]] = defaultdict(list)
    for n, line in enumerate(lines):
        for sku_id in line.skus:
            by_key[(sku_id, line.region)].append(n)
    groups: set[tuple[int, ...]] = set()
    for pair in strong:
        first, second = sorted(pair)
        for region in Region:
            sides = [by_key.get((first, region), []), by_key.get((second, region), [])]
            if not sides[0] or not sides[1]:
                continue
            cells: defaultdict[tuple[int, TargetSegment], tuple[set[int], set[int]]] = defaultdict(
                lambda: (set(), set())
            )
            for side, members in enumerate(sides):
                for n in members:
                    line = lines[n]
                    everyone = line.target_segment is TargetSegment.ALL_CUSTOMERS
                    for week in range(line.start_week, line.start_week + line.duration_weeks):
                        for segment in _SEGMENTS if everyone else [line.target_segment]:
                            cells[(week, segment)][side].add(n)
            for one, other in cells.values():
                if one and other:
                    groups.add(tuple(sorted(one | other)))
    return sorted(groups)


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _paise_up(rupees: np.ndarray) -> np.ndarray:
    """Rupees in whole paise, rounded up: a constraint on them is never looser than exact."""
    return np.ceil(rupees * PAISE - _ROUNDING).astype(np.int64)


def _dot(coefficients: np.ndarray, variables: Sequence[cp_model.IntVar]) -> cp_model.LinearExpr:
    terms = [(variable, int(c)) for variable, c in zip(variables, coefficients, strict=True) if c]
    return cp_model.LinearExpr.weighted_sum([v for v, _ in terms], [c for _, c in terms])
