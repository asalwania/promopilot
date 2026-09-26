"""The planning session's planner (E6): promo option generation, then the CP-SAT optimiser.

For a planning request it generates every promo option of the scope and promo window on the
latest demand model and the live relations model (ADR 0035), selects the plan with `solve`
(ADR 0036) and turns the result into plan revision 1: each plan line with its expected
numbers and why it was chosen, the solver status and objective, the binding constraints and
the best options left out (ADR 0038). E8's planner agent drives the same work through the
`generate_candidates` and `run_optimizer` tools instead.
"""

import asyncio
from typing import Protocol

import pandas as pd

from promopilot.agents.tools.estimate_demand import DemandModelSource
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.domain import CompanyPolicy, PlanningRequest, PlanRevision, PlanRevisionLine
from promopilot.optimizer import (
    FittedOptionFacts,
    OptionContext,
    SolverSettings,
    generate_options,
    solve,
)


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
    ) -> None:
        self._demand_models = demand_models
        self._relations_models = relations_models
        self._data = data
        self._policy = policy
        self._settings = settings
        self._seed = seed

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
        table = options.table
        return PlanRevision(
            number=1,
            lines=tuple(
                PlanRevisionLine(
                    line=options.lines[row],
                    expected_units=float(table["units"].iloc[row]),
                    promo_cost=float(table["promo_cost"].iloc[row]),
                    expected_incremental_profit=float(table["incremental_profit"].iloc[row]),
                    why_chosen=why,
                )
                for row, why in zip(result.selected, result.why_chosen, strict=True)
            ),
            solver_status=result.status,
            objective=result.objective,
            binding_constraints=result.binding_constraints,
            not_selected=result.not_selected,
        )
