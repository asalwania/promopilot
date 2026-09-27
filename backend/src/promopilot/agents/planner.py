"""The planning session's planner (E6): promo option generation, then the CP-SAT optimiser.

For a planning request it generates every promo option of the scope and promo window on the
latest demand model and the live relations model (ADR 0035), selects the plan with `solve`
(ADR 0036) and turns the result into plan revision 1: each plan line with its expected
numbers, why it was chosen and how the other mechanisms compare (ADR 0041), the solver status
and objective, the binding constraints and the best options left out (ADR 0038). The plan is
then simulated with the session's simulation settings and the result stored on the revision
(ADR 0042). E8's planner agent drives the same work through the `generate_candidates`,
`run_optimizer`, `compare_mechanisms` and `simulate_plan` tools instead.
"""

import asyncio
from typing import Protocol

import pandas as pd

from promopilot.agents.tools.estimate_demand import DemandModelSource
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.domain import CompanyPolicy, PlanningRequest, PlanRevision, PlanRevisionLine
from promopilot.mechanisms import ComparisonContext, compare
from promopilot.optimizer import (
    FittedOptionFacts,
    OptionContext,
    SolverSettings,
    generate_options,
    solve,
)
from promopilot.simulator import SimulationInputs, SimulationSettings, simulate


class PlanningError(Exception):
    """The planning request cannot be planned now (no trained model, or no data)."""


class PlannerData(Protocol):
    """The reads the planner makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...


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

    async def plan(self, request: PlanningRequest) -> PlanRevision:
        """Plan revision 1 for the request. Raises `PlanningError` when no model is trained
        or the as-of week has no inventory snapshot."""
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
        )
        # Generation and solving are CPU-bound: keep the event loop free (ADR 0025).
        options = await asyncio.to_thread(generate_options, request, context)
        result = await asyncio.to_thread(
            solve,
            request,
            options,
            FittedOptionFacts(context),
            self._policy,
            settings=self._settings,
            seed=self._seed,
        )
        # Simulation is CPU-bound too; it samples the plan's own SKUs on the same demand model.
        simulation = await asyncio.to_thread(
            simulate,
            result.plan,
            SimulationInputs(demand=demand[1], stock=context.stock, policy=self._policy),
            n_runs=self._simulation.n_runs,
            seed=self._simulation.seed,
        )
        table = options.table
        # Each line's mechanisms are compared on the same options the optimiser chose from.
        comparing = ComparisonContext(
            options=options, relations=context.relations, products=context.products
        )
        lines = []
        for row, why in zip(result.selected, result.why_chosen, strict=True):
            line = options.lines[row]
            lines.append(
                PlanRevisionLine(
                    line=line,
                    expected_units=float(table["units"].iloc[row]),
                    promo_cost=float(table["promo_cost"].iloc[row]),
                    expected_incremental_profit=float(table["incremental_profit"].iloc[row]),
                    why_chosen=why,
                    mechanism_comparison=compare(line.sku_id, line.region, comparing, chosen=line),
                )
            )
        return PlanRevision(
            number=1,
            lines=tuple(lines),
            solver_status=result.status,
            objective=result.objective,
            binding_constraints=result.binding_constraints,
            not_selected=result.not_selected,
            simulation=simulation,
        )
