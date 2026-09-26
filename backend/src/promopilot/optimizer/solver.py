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

Beside the plan, `solve` reports (ADR 0038):

- the binding constraints: the budget, the margin and each promoted-SKU cap whose removal
  gives a strictly better objective, found by re-solving without it from the plan found;
- why each plan line was chosen: the positive parts of its value, and whether it is the
  best eligible option of its SKU and region;
- the best option of up to five SKUs and regions with no plan line, with every rule it
  breaks alone or added to the plan.

The solver runs with a fixed seed and, by default, one worker; with more workers it
interleaves their search, so the same input gives the same plan whenever the solver proves
optimality within its time limit.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from ortools.sat.python import cp_model

from promopilot.domain import (
    BindingConstraint,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    NotSelectedOption,
    NotSelectedReason,
    PlanLine,
    PlanningRequest,
    PromoPlan,
    Region,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
    TargetSegment,
    WhyChosen,
)
from promopilot.economics import effective_unit_price
from promopilot.guardrails import SkuFacts
from promopilot.optimizer.options import PromoOptions

PAISE = 100
_EPSILON = 1e-9
_ROUNDING = 1e-6
"""Paise lost to float noise before rounding a coefficient up or down."""


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
    """The selected promo plan, how it was found and why (ADR 0036, ADR 0038). Money in
    rupees."""

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
    binding_constraints: tuple[BindingConstraint, ...] = ()
    """Constraints whose removal gives a strictly better objective; only for OPTIMAL plans."""
    why_chosen: tuple[WhyChosen, ...] = ()
    """One per plan line, in the plan's order."""
    not_selected: tuple[NotSelectedOption, ...] = ()
    """The best option of up to NOT_SELECTED_SHOWN SKUs and regions with no plan line."""


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
    """The promo plan that maximises the objective for the planning request (ADR 0036), with
    its binding constraints, why each line was chosen and the best options left out (ADR
    0038)."""
    settings = settings or SolverSettings()
    problem = _Problem.of(request, options, facts, policy)
    outcome = problem.solve(settings, seed)
    if outcome.status == cp_model.INFEASIBLE:
        return OptimisationResult(
            SolveStatus.INFEASIBLE, 0.0, PromoPlan(), (), 0.0, len(problem.lines), 0
        )
    # No plan found in time leaves the empty plan, which keeps every constraint here (#36
    # adds clearance targets, which it may not).
    found = outcome.status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    picked = outcome.picked if found else []
    status = SolveStatus.OPTIMAL if outcome.status == cp_model.OPTIMAL else SolveStatus.FEASIBLE
    charged = outcome.charged if found else 0
    objective = int(problem.value[picked].sum()) - charged
    return OptimisationResult(
        status=status,
        objective=objective / PAISE,
        plan=PromoPlan(lines=tuple(problem.lines[n] for n in picked)),
        selected=tuple(problem.eligible[n] for n in picked),
        pairwise_cannibalisation=charged / PAISE,
        eligible=len(problem.lines),
        pairs=len(problem.pairs) if found else 0,
        binding_constraints=(
            problem.binding(picked, objective, settings, seed)
            if status is SolveStatus.OPTIMAL
            else ()
        ),
        why_chosen=tuple(problem.why_chosen(n) for n in picked),
        not_selected=problem.not_selected(picked),
    )


@dataclass(frozen=True)
class _Limit:
    """One plan-level constraint of the model: the budget, the margin, or the promoted-SKU
    cap of one category and region."""

    kind: ConstraintKind
    group: tuple[str, Region] | None = None


_BUDGET = _Limit(ConstraintKind.MARKETING_BUDGET)
_MARGIN = _Limit(ConstraintKind.MINIMUM_MARGIN)


@dataclass(frozen=True)
class _Outcome:
    status: cp_model.CpSolverStatus
    picked: list[int]
    """Selected eligible options, as indices into `_Problem.lines`."""
    charged: int
    """Pairwise terms of selected pairs, in paise."""


@dataclass
class _Problem:
    """The eligible options and every coefficient of the model, in integer paise."""

    request: PlanningRequest
    options: PromoOptions
    facts: OptionFacts
    policy: CompanyPolicy
    eligible: list[int]
    """Eligible options' rows in the candidate table."""
    lines: list[PlanLine]
    value: np.ndarray
    cost: np.ndarray
    """Promo cost, rounded up."""
    budget: int
    """The marketing budget, rounded down."""
    minimum: float
    """The minimum margin applied: the request's, never below the margin floor."""
    short: np.ndarray
    """minimum x revenue - gross profit, rounded up: the margin constraint's coefficients."""
    groups: dict[tuple[str, Region], list[int]]
    """(category, region) -> eligible options promoting a SKU there, once per SKU."""
    pairs: list[tuple[int, int]]
    charges: np.ndarray
    terms: dict[tuple[int, int], int]
    """Pairwise terms in paise, zero or not, by candidate-table rows (lower row first)."""

    @classmethod
    def of(
        cls,
        request: PlanningRequest,
        options: PromoOptions,
        facts: OptionFacts,
        policy: CompanyPolicy,
    ) -> "_Problem":
        eligible = _eligible(request, options, facts, policy)
        lines = [options.lines[n] for n in eligible]
        table = options.table.iloc[eligible]
        minimum = max(request.min_margin or 0.0, policy.margin_floor)
        groups: defaultdict[tuple[str, Region], list[int]] = defaultdict(list)
        for n, line in enumerate(lines):
            for sku_id in line.skus:
                groups[(facts.sku(sku_id, line.region).category, line.region)].append(n)
        pairs, charges, computed = _pairs(lines, facts)
        return cls(
            request=request,
            options=options,
            facts=facts,
            policy=policy,
            eligible=eligible,
            lines=lines,
            value=np.rint(table["value"].to_numpy(float) * PAISE).astype(np.int64),
            cost=_paise_up(table["promo_cost"].to_numpy(float)),
            budget=math.floor(request.marketing_budget * PAISE + _ROUNDING),
            minimum=minimum,
            short=_paise_up(
                minimum * table["revenue"].to_numpy(float) - table["gross_profit"].to_numpy(float)
            ),
            groups=dict(groups),
            pairs=pairs,
            charges=charges,
            terms={_key(eligible[i], eligible[j]): term for (i, j), term in computed.items()},
        )

    def solve(
        self,
        settings: SolverSettings,
        seed: int,
        *,
        drop: _Limit | None = None,
        hint: Sequence[int] = (),
    ) -> _Outcome:
        """Solve the model, without the `drop` constraint, starting from the `hint` plan."""
        model = cp_model.CpModel()
        x = [model.new_bool_var(f"x{n}") for n in range(len(self.lines))]
        occupied: defaultdict[tuple[str, Region], list[cp_model.IntVar]] = defaultdict(list)
        for chosen, line in zip(x, self.lines, strict=True):
            for sku_id in line.skus:
                occupied[(sku_id, line.region)].append(chosen)
        for variables in occupied.values():
            model.add_at_most_one(variables)
        cap = self.policy.max_promoted_skus_per_category_per_region
        for group, members in self.groups.items():
            if drop != _Limit(ConstraintKind.MAX_PROMOTED_SKUS, group):
                model.add(sum(x[n] for n in members) <= cap)
        if drop != _BUDGET:
            model.add(_dot(self.cost, x) <= self.budget)
        if drop != _MARGIN:
            model.add(_dot(self.short, x) <= 0)

        y = []
        for i, j in self.pairs:
            both = model.new_bool_var(f"y{i}_{j}")
            model.add_bool_and([x[i], x[j]]).only_enforce_if(both)
            model.add_bool_or([x[i].Not(), x[j].Not()]).only_enforce_if(both.Not())
            y.append(both)
        model.maximize(_dot(np.concatenate([self.value, -self.charges]), [*x, *y]))
        if hint:
            hinted = set(hint)
            for n, chosen in enumerate(x):
                model.add_hint(chosen, n in hinted)
            for (i, j), both in zip(self.pairs, y, strict=True):
                model.add_hint(both, i in hinted and j in hinted)

        solver = cp_model.CpSolver()
        solver.parameters.random_seed = seed
        solver.parameters.num_workers = settings.workers
        solver.parameters.interleave_search = settings.workers > 1
        solver.parameters.max_time_in_seconds = settings.time_limit_seconds
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _Outcome(status, [], 0)
        picked = [n for n, chosen in enumerate(x) if solver.boolean_value(chosen)]
        charged = int(
            sum(c for c, both in zip(self.charges, y, strict=True) if solver.boolean_value(both))
        )
        return _Outcome(status, picked, charged)

    def binding(
        self, picked: list[int], objective: int, settings: SolverSettings, seed: int
    ) -> tuple[BindingConstraint, ...]:
        """Each constraint whose removal gives a strictly better objective: re-solved without
        it from the current plan, so a gain found is proven even if the re-solve times out."""
        cap = self.policy.max_promoted_skus_per_category_per_region
        limits = [_BUDGET, _MARGIN] + [
            _Limit(ConstraintKind.MAX_PROMOTED_SKUS, group)
            for group, members in sorted(self.groups.items())
            if len(members) > cap
        ]
        found = []
        for limit in limits:
            relaxed = self.solve(settings, seed, drop=limit, hint=picked)
            if relaxed.status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                continue
            gain = int(self.value[relaxed.picked].sum()) - relaxed.charged - objective
            if gain >= 1:
                found.append(self._named(limit, gain))
        return tuple(found)

    def _named(self, limit: _Limit, gain: int) -> BindingConstraint:
        if limit.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            assert limit.group is not None
            category, region = limit.group
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.COMPANY_POLICY,
                limit=self.policy.max_promoted_skus_per_category_per_region,
                category=category,
                region=region,
                objective_gain=gain / PAISE,
            )
        if limit.kind is ConstraintKind.MARKETING_BUDGET:
            return BindingConstraint(
                kind=limit.kind,
                source=ConstraintSource.BRIEF,
                limit=self.request.marketing_budget,
                objective_gain=gain / PAISE,
            )
        brief = self.request.min_margin
        from_brief = brief is not None and brief > self.policy.margin_floor
        return BindingConstraint(
            kind=ConstraintKind.MINIMUM_MARGIN if from_brief else ConstraintKind.MARGIN_FLOOR,
            source=ConstraintSource.BRIEF if from_brief else ConstraintSource.COMPANY_POLICY,
            limit=self.minimum,
            objective_gain=gain / PAISE,
        )

    def why_chosen(self, n: int) -> WhyChosen:
        """The positive parts of a plan line's value, and whether it is the best eligible
        option of its SKU and region."""
        row = self.options.table.iloc[self.eligible[n]]
        parts = (
            (SelectionReasonCode.INCREMENTAL_PROFIT, float(row["incremental_profit"])),
            (SelectionReasonCode.CLEARANCE_VALUE, float(row["clearance_value"])),
            (SelectionReasonCode.HALO, float(row["halo_profit"])),
        )
        line = self.lines[n]
        rivals = [
            m
            for m, other in enumerate(self.lines)
            if (other.sku_id, other.region) == (line.sku_id, line.region)
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
        return tuple(
            self._why_not(row, int(values[row]), picked, plan_rows, terms) for row in shown
        )

    def _terms(self, pairs: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
        """Pairwise terms in paise for pairs of candidate rows that could run together."""
        lines = self.options.lines
        wanted = sorted(
            {
                _key(a, b)
                for a, b in pairs
                if _together(lines[a], lines[b]) and _key(a, b) not in self.terms
            }
        )
        if wanted:
            computed = self.facts.pairwise_cannibalisation(
                [(lines[a], lines[b]) for a, b in wanted]
            )
            charges = np.rint(np.asarray(computed, dtype=float) * PAISE).astype(np.int64)
            self.terms.update(zip(wanted, (int(c) for c in charges), strict=True))
        return {key: self.terms[key] for key in (_key(a, b) for a, b in pairs) if key in self.terms}

    def _why_not(
        self,
        row: int,
        value: int,
        picked: list[int],
        plan_rows: list[int],
        terms: dict[tuple[int, int], int],
    ) -> NotSelectedOption:
        options, table = self.options, self.options.table
        line = options.lines[row]
        reasons = []
        if value < 1:
            reasons.append(NotSelectedReason.LOW_UPLIFT)
        number = {name: float(amount) for name, amount in table.iloc[row].items()}
        over = number["p90_units"] > number["available_stock"] + _EPSILON
        partner_over = number["partner_p90_units"] > number["partner_available_stock"] + _EPSILON
        if over or (line.bundle_partner_sku_id is not None and partner_over):
            reasons.append(NotSelectedReason.OUT_OF_STOCK)
        if not _in_window(line, self.request) or not _priced_within_policy(
            line, self.facts, self.policy
        ):
            reasons.append(NotSelectedReason.BREAKS_POLICY)
        cost = _paise_up(np.array([number["promo_cost"]]))[0]
        if int(self.cost[picked].sum()) + cost > self.budget:
            reasons.append(NotSelectedReason.OVER_BUDGET)
        short = _paise_up(np.array([self.minimum * number["revenue"] - number["gross_profit"]]))[0]
        if int(self.short[picked].sum()) + short > 0:
            reasons.append(NotSelectedReason.BREAKS_MARGIN)
        if self._over_cap(line, picked):
            reasons.append(NotSelectedReason.MAX_PROMOTED_SKUS)
        losing = [
            (other, terms[_key(row, other)])
            for other in plan_rows
            if terms.get(_key(row, other), 0) > 0
        ]
        cannibalises: tuple[str, ...] = ()
        if value >= 1 and value - sum(term for _, term in losing) < 1:
            reasons.append(NotSelectedReason.CANNIBALISES)
            cannibalises = tuple(sorted({options.lines[other].sku_id for other, _ in losing}))
        if not reasons:
            # Adding it would keep every rule and gain: only a plan not proven best allows it.
            reasons.append(NotSelectedReason.TIME_LIMIT)
        return NotSelectedOption(
            option=line,
            value=number["value"],
            reasons=tuple(reasons),
            cannibalises=cannibalises,
        )

    def _over_cap(self, line: PlanLine, picked: list[int]) -> bool:
        chosen = set(picked)
        cap = self.policy.max_promoted_skus_per_category_per_region
        adds: defaultdict[tuple[str, Region], int] = defaultdict(int)
        for sku_id in line.skus:
            adds[(self.facts.sku(sku_id, line.region).category, line.region)] += 1
        for group, extra in adds.items():
            promoted = sum(1 for n in self.groups.get(group, []) if n in chosen)
            if promoted + extra > cap:
                return True
        return False


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
    kept = []
    for n in np.flatnonzero(worth & fits):
        line = options.lines[n]
        if line.bundle_partner_sku_id is not None and not partner_fits[n]:
            continue
        if _in_window(line, request) and _priced_within_policy(line, facts, policy):
            kept.append(int(n))
    return kept


def _in_window(line: PlanLine, request: PlanningRequest) -> bool:
    window = request.promo_window
    end_week = line.start_week + line.duration_weeks - 1
    return line.start_week >= window.start_week and end_week <= window.end_week


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
) -> tuple[list[tuple[int, int]], np.ndarray, dict[tuple[int, int], int]]:
    """The pairs of lines that could run together with a non-zero pairwise term in whole
    paise, and every term computed, zero or not."""
    candidates = _overlapping(lines)
    if not candidates:
        return [], np.zeros(0, dtype=np.int64), {}
    terms = facts.pairwise_cannibalisation([(lines[i], lines[j]) for i, j in candidates])
    charges = np.rint(np.asarray(terms, dtype=float) * PAISE).astype(np.int64)
    keep = np.flatnonzero(charges != 0)
    computed = {pair: int(charge) for pair, charge in zip(candidates, charges, strict=True)}
    return [candidates[k] for k in keep], charges[keep], computed


def _overlapping(lines: Sequence[PlanLine]) -> list[tuple[int, int]]:
    """Pairs that could run together (`_together`), region by region."""
    by_region: defaultdict[Region, list[int]] = defaultdict(list)
    for n, line in enumerate(lines):
        by_region[line.region].append(n)
    found = []
    for members in by_region.values():
        for k, i in enumerate(members):
            for j in members[k + 1 :]:
                if _together(lines[i], lines[j]):
                    found.append((i, j))
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
    return cp_model.LinearExpr.weighted_sum(variables, [int(c) for c in coefficients])
