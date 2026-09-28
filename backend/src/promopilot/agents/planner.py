"""The planning session's planner (E6): promo option generation, then the CP-SAT optimiser.

For a planning request it generates every promo option of the scope and promo window on the
latest demand model and the live relations model (ADR 0035), selects the plan with `solve`
(ADR 0036) and turns the result into plan revision 1: each plan line with its expected
numbers, why it was chosen and how the other mechanisms compare (ADR 0041), the solver status
and objective, the binding constraints and the best options left out (ADR 0038), with any
clearance shortfall and any brief value that would have loosened company policy (ADR 0040).
A request no plan can reach every clearance target of is infeasible: the revision keeps the
closest plan and the smallest relaxation of the brief's constraints (ADR 0044).
The latest competitor gaps give undercut KVIs their price-match options and the KVI price
tolerance its competitor prices (ADR 0031). The plan is then simulated with the session's
simulation settings and the result stored on the revision (ADR 0042). E8's planner agent
drives the same work through the `generate_candidates`, `run_optimizer`,
`compare_mechanisms` and `simulate_plan` tools instead; until then this is the agent graph's
Planner node (ADR 0046), and it also returns the revision's plan facts for the Critic.
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import pandas as pd

from promopilot.agents.state import DegradedReason
from promopilot.agents.tools.estimate_demand import DemandModelSource
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.competitors import read_competitor_gaps
from promopilot.domain import (
    CompanyPolicy,
    LineCrossEffect,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Segment,
    SegmentUplift,
    uplift_pct,
)
from promopilot.guardrails import PlanFacts
from promopilot.mechanisms import ComparisonContext, compare
from promopilot.models.demand import DemandModel, PredictionContext
from promopilot.models.relations import line_effects
from promopilot.optimizer import (
    CandidateStore,
    FittedOptionFacts,
    OptimisationResult,
    OptionContext,
    OptionFacts,
    PromoOptions,
    SolverSettings,
    generate_options,
    plan_facts,
    solve,
)
from promopilot.simulator import SimulationInputs, SimulationSettings, simulate


class PlanningError(Exception):
    """The planning request cannot be planned now (no trained model, or no data)."""


@dataclass(frozen=True)
class PlannedRevision:
    """A plan revision and the plan-time numbers its plan was chosen on, which plan
    validation reads (ADR 0028)."""

    revision: PlanRevision
    facts: PlanFacts
    notes: tuple[str, ...] = ()
    """The planner's explanation of the plan, from tool outputs only (ADR 0049)."""
    degraded: DegradedReason | None = None
    """Why the default sequence planned it instead of the planner agent (ADR 0049)."""


class PlannerData(Protocol):
    """The reads the planner makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...
    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame: ...


class OptimisingPlanner:
    """Plans a planning request with option generation and the optimiser."""

    def __init__(
        self,
        demand_models: DemandModelSource,
        relations_models: RelationsSource,
        data: PlannerData,
        *,
        policy: CompanyPolicy,
        settings: SolverSettings,
        seed: int,
        simulation: SimulationSettings,
    ) -> None:
        self._demand_models = demand_models
        self._relations_models = relations_models
        self._data = data
        self._policy = policy
        self._settings = settings
        self._seed = seed
        self._simulation = simulation

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        """Plan revision 1 for the request, with its plan facts. Raises `PlanningError` when
        no model is trained, the as-of week has no inventory snapshot, or the request names a
        clearance target outside its scope."""
        loaded = await self._load(request)
        # Generation and solving are CPU-bound: keep the event loop free (ADR 0025).
        try:
            options = await asyncio.to_thread(generate_options, request, loaded.context)
        except ValueError as error:
            raise PlanningError(str(error)) from error
        facts = FittedOptionFacts(loaded.context)
        result = await asyncio.to_thread(
            solve,
            request,
            options,
            facts,
            self._policy,
            settings=self._settings,
            seed=self._seed,
        )
        return await self._revision(loaded, options, facts, result)

    async def revise(
        self,
        request: PlanningRequest,
        options: PromoOptions,
        facts: OptionFacts,
        result: OptimisationResult,
    ) -> PlannedRevision:
        """Plan revision 1 from an optimiser result already found on these options (the
        planner agent's `run_optimizer`, ADR 0049): compared and simulated as `plan` does,
        without solving again. Raises `PlanningError` as `plan` does."""
        return await self._revision(await self._load(request), options, facts, result)

    async def _load(self, request: PlanningRequest) -> "_Loaded":
        demand = await self._demand_models.get()
        relations = await self._relations_models.get()
        if demand is None or relations is None:
            raise PlanningError(
                "no demand model, or no relations model fitted on it, is trained yet: "
                "run make train"
            )
        stores = await self._data.stores()
        try:
            snapshot = await self._data.inventory(request.as_of_week)
        except LookupError as error:
            raise PlanningError(str(error)) from error
        context = OptionContext(
            demand_model=demand[1],
            relations=relations[1],
            products=await self._data.products(),
            stock=pooled_stock(snapshot, stores, self._policy),
            policy=self._policy,
            competitor_gaps=await read_competitor_gaps(
                self._data,
                as_of_week=request.as_of_week,
                policy=self._policy,
                regions=request.scope.regions,
            ),
        )
        return _Loaded(context=context, demand=demand[1])

    async def _revision(
        self,
        loaded: "_Loaded",
        options: PromoOptions,
        facts: OptionFacts,
        result: OptimisationResult,
    ) -> PlannedRevision:
        context = loaded.context
        # Simulation is CPU-bound too; it samples the plan's own SKUs on the same demand model.
        simulation = await asyncio.to_thread(
            simulate,
            result.plan,
            SimulationInputs(demand=loaded.demand, stock=context.stock, policy=self._policy),
            n_runs=self._simulation.n_runs,
            seed=self._simulation.seed,
        )
        table = options.table
        # Each line's mechanisms are compared on the same options the optimiser chose from.
        comparing = ComparisonContext(
            options=options, relations=context.relations, products=context.products
        )
        chosen = [options.lines[row] for row in result.selected]
        details = await asyncio.to_thread(_line_details, chosen, context)
        lines = []
        for row, why, line, (segments, effects) in zip(
            result.selected, result.why_chosen, chosen, details, strict=True
        ):
            units = float(table["units"].iloc[row])
            baseline = float(table["baseline_units"].iloc[row])
            lines.append(
                PlanRevisionLine(
                    line=line,
                    expected_units=units,
                    promo_cost=float(table["promo_cost"].iloc[row]),
                    expected_incremental_profit=float(table["incremental_profit"].iloc[row]),
                    why_chosen=why,
                    mechanism_comparison=compare(line.sku_id, line.region, comparing, chosen=line),
                    baseline_units=baseline,
                    uplift_pct=uplift_pct(units, baseline),
                    segments=segments,
                    cross_effects=effects,
                )
            )
        revision = PlanRevision(
            number=1,
            lines=tuple(lines),
            solver_status=result.status,
            objective=result.objective,
            binding_constraints=result.binding_constraints,
            not_selected=result.not_selected,
            simulation=simulation,
            clearance_shortfalls=result.clearance_shortfalls,
            policy_findings=result.policy_findings,
            relaxation=result.relaxation,
        )
        return PlannedRevision(revision, plan_facts(options, result.selected, facts))


def _line_details(
    lines: list[PlanLine], context: OptionContext
) -> list[tuple[tuple[SegmentUplift, ...], tuple[LineCrossEffect, ...]]]:
    """Each plan line's expected units by segment (F-03 AC2), from the same prediction its
    numbers came from, and every other SKU it moves in its region (ADR 0033)."""
    if not lines:
        return []
    prediction = context.demand_model.predict(
        lines, PredictionContext(policy=context.policy, competitor_prices=context.competitor_prices)
    )
    order = {segment.value: n for n, segment in enumerate(Segment)}
    by_option = prediction.segments.groupby("option")
    effects = line_effects(lines, context.relations, context.demand_model, context.products)
    by_line = effects.groupby("line")
    details = []
    for n in range(len(lines)):
        rows = by_option.get_group(n)
        segments = tuple(
            sorted(
                (
                    SegmentUplift.of(Segment(segment), units=units, baseline_units=baseline)
                    for segment, units, baseline in zip(
                        rows["segment"].astype(str),
                        rows["units"].to_numpy(dtype=float),
                        rows["baseline_units"].to_numpy(dtype=float),
                        strict=True,
                    )
                ),
                key=lambda segment: order[segment.segment.value],
            )
        )
        moved = by_line.get_group(n) if n in by_line.groups else effects.iloc[0:0]
        details.append(
            (
                segments,
                tuple(
                    LineCrossEffect(sku_id=sku_id, units_change_pct=pct, profit_change=change)
                    for sku_id, pct, change in zip(
                        moved["sku_id"].astype(str),
                        moved["units_change_pct"].to_numpy(dtype=float),
                        moved["profit_change"].to_numpy(dtype=float),
                        strict=True,
                    )
                ),
            )
        )
    return details


@dataclass(frozen=True)
class _Loaded:
    context: OptionContext
    demand: DemandModel


class StoredRevisions:
    """The plan revision of a stored candidate set's latest optimiser solution: the planner
    agent's final plan (ADR 0049), built in process, never from the tool's JSON."""

    def __init__(self, store: CandidateStore, planner: OptimisingPlanner) -> None:
        self._store = store
        self._planner = planner

    async def revision(self, candidate_set_id: UUID) -> PlannedRevision | None:
        """None when the set is no longer stored or `run_optimizer` never solved it. Raises
        `PlanningError` when no model is trained or the inventory snapshot is missing."""
        stored = self._store.get(candidate_set_id)
        solution = self._store.solution(candidate_set_id)
        if stored is None or solution is None:
            return None
        return await self._planner.revise(stored.request, stored.options, stored.facts, solution)
