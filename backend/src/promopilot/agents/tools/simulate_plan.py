"""`simulate_plan`: the Monte Carlo ranges of a promo plan's outcomes and its stock-out risk.

The planner passes the plan lines; the simulator samples them on the latest demand model and
caps units at the pooled available stock of the bound as-of week (SPEC §9.5, ADR 0042). The seed
and the default number of runs are bound when the tool is built, so the LLM cannot change the
samples; it may only ask for more or fewer runs within the simulator's bounds.
"""

import asyncio
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.estimate_demand import DemandModelSource, ModelVersion
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import CompanyPolicy, PlanLine, PlanSimulation, PromoPlan
from promopilot.simulator import (
    MAX_RUNS,
    MIN_RUNS,
    SimulationInputs,
    SimulationSettings,
    simulate,
)

MAX_LINES = 200

DESCRIPTION = (
    "Simulate a promo plan many times (Monte Carlo): each run samples the demand model's "
    "elasticities, mechanism effects and other terms within their uncertainty, then weekly "
    "demand noise per store and segment. Units are capped at each SKU's pooled available "
    "stock in the region. Returns P10/P50/P90 of units, revenue, gross profit, margin, "
    "sell-through and promo spend for each plan line (over its promo weeks; units and "
    "sell-through are the anchor SKU's, money includes a BUNDLE's partner) and for the whole "
    "plan, the stock-out probability of each line (the share of runs whose demand reached "
    "the available stock) and of each region (at least one of its lines ran out). The seed is "
    "fixed, so the same plan gives the same result."
)


class SimulationData(Protocol):
    """The reads this tool makes (`promopilot.data.RetailData`)."""

    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...


class SimulatePlanInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: list[PlanLine] = Field(
        min_length=1,
        max_length=MAX_LINES,
        description="The plan's lines: one per SKU per region at most, a BUNDLE partner included.",
    )
    n_runs: int | None = Field(
        default=None,
        ge=MIN_RUNS,
        le=MAX_RUNS,
        description="Runs to simulate; omit for the default.",
    )


class SimulatePlanOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    demand_model: ModelVersion
    as_of_week: int
    simulation: PlanSimulation


def simulate_plan_tool(
    demand_models: DemandModelSource,
    data: SimulationData,
    as_of_week: AsOfWeekSource,
    *,
    policy: CompanyPolicy,
    defaults: SimulationSettings,
) -> Tool[SimulatePlanInput, SimulatePlanOutput]:
    async def simulate_plan(arguments: SimulatePlanInput) -> SimulatePlanOutput:
        try:
            plan = PromoPlan(lines=tuple(arguments.lines))
        except ValidationError as error:
            raise ToolCallError("invalid_input", _message(error)) from error
        week = await current_as_of_week(as_of_week)
        for planned in plan.lines:
            if planned.start_week < week:
                raise ToolCallError(
                    "invalid_input",
                    f"{planned.sku_id} in {planned.region} starts in week {planned.start_week}, "
                    f"before the as-of week {week}",
                )
        demand = await demand_models.get()
        if demand is None:
            raise ToolCallError("model_unavailable", "no demand model is trained yet")
        try:
            snapshot = await data.inventory(week)
        except LookupError as error:
            raise ToolCallError("data_unavailable", str(error)) from error
        inputs = SimulationInputs(
            demand=demand[1],
            stock=pooled_stock(snapshot, await data.stores(), policy),
            policy=policy,
        )
        try:
            # Sampling is CPU-bound: keep the event loop free (ADR 0025).
            simulation = await asyncio.to_thread(
                simulate,
                plan,
                inputs,
                n_runs=arguments.n_runs or defaults.n_runs,
                seed=defaults.seed,
            )
        except ValueError as error:
            raise ToolCallError("invalid_input", str(error)) from error
        entry = demand[0]
        return SimulatePlanOutput(
            demand_model=ModelVersion(
                model_id=entry.model_id, version=entry.version, as_of_week=entry.as_of_week
            ),
            as_of_week=week,
            simulation=simulation,
        )

    return Tool(
        name="simulate_plan",
        description=DESCRIPTION,
        input_type=SimulatePlanInput,
        output_type=SimulatePlanOutput,
        handler=simulate_plan,
    )


def _message(error: ValidationError) -> str:
    return "; ".join(str(issue["msg"]).removeprefix("Value error, ") for issue in error.errors())
