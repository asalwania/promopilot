"""`run_optimizer`: select the promo plan from a candidate set with the CP-SAT optimiser.

The planner passes the `candidate_set_id` that `generate_candidates` returned; the full set,
with the facts and models it was generated with, is read from the in-process
`CandidateStore` (ADR 0035, ADR 0036). Company policy, the solver's time limit and workers,
and its seed are bound when the tool is built; the LLM never sets them. Every number comes
from the stored options and the solver.
"""

import asyncio
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import CompanyPolicy, PlanLine
from promopilot.economics import blended_margin
from promopilot.optimizer import CandidateStore, SolverSettings, SolveStatus, solve

DESCRIPTION = (
    "Select the promo plan from a candidate set made by generate_candidates: at most one "
    "plan line per SKU per region (a BUNDLE's partner included), maximising incremental "
    "profit net of cannibalisation (including what two substitutes lose when promoted "
    "together) plus halo and clearance value. The plan keeps total promo cost within the "
    "marketing budget, the blended margin at or above the minimum margin (never below the "
    "company-policy margin floor), and at most the company-policy number of promoted SKUs "
    "per category per region. Only options that pay for themselves alone are selected. "
    "Returns the solver status (OPTIMAL, FEASIBLE when the time limit ran out first, "
    "INFEASIBLE), the objective, each selected plan line with its numbers, and the plan's "
    "totals. A candidate_set_id that is no longer stored must be regenerated."
)


class RunOptimizerInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_set_id: UUID = Field(description="From generate_candidates.")


class OptimizedLine(BaseModel):
    """A selected plan line's numbers, as its promo option predicted them (rupees, units
    over its promo weeks)."""

    model_config = ConfigDict(frozen=True)

    option: PlanLine
    units: float
    p90_units: float
    available_stock: float
    promo_cost: float
    revenue: float
    gross_profit: float
    incremental_profit: float
    cannibalised_profit: float
    halo_profit: float
    clearance_value: float
    value: float = Field(
        description="incremental_profit - cannibalised_profit + halo_profit + clearance_value"
    )


class RunOptimizerOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_set_id: UUID
    status: SolveStatus
    objective: float = Field(
        description="The lines' values less what selected substitute pairs lose together."
    )
    lines: list[OptimizedLine]
    total_promo_cost: float
    marketing_budget: float
    blended_margin: float | None = Field(description="None when no line is selected.")
    min_margin: float = Field(
        description="The minimum margin applied: the request's, never below the margin floor."
    )
    pairwise_cannibalisation: float = Field(
        description="What the selected substitute pairs lose together (negative: they gain)."
    )
    candidate_options: int
    eligible_options: int = Field(
        description="Candidate options that pay for themselves alone and keep every per-line rule."
    )
    pairs: int = Field(description="Pairs of eligible options that interact.")


_LINE_COLUMNS = [name for name in OptimizedLine.model_fields if name != "option"]


def run_optimizer_tool(
    store: CandidateStore,
    *,
    policy: CompanyPolicy,
    settings: SolverSettings,
    seed: int,
) -> Tool[RunOptimizerInput, RunOptimizerOutput]:
    async def run_optimizer(arguments: RunOptimizerInput) -> RunOptimizerOutput:
        stored = store.get(arguments.candidate_set_id)
        if stored is None:
            raise ToolCallError(
                "invalid_input",
                f"no candidate set {arguments.candidate_set_id} is stored (it may have been "
                "dropped or made before a restart); call generate_candidates again",
            )
        request, options = stored.request, stored.options
        # Solving is CPU-bound: keep the event loop free (ADR 0025).
        result = await asyncio.to_thread(
            solve, request, options, stored.facts, policy, settings=settings, seed=seed
        )
        table = options.table.iloc[list(result.selected)]
        lines = [
            OptimizedLine.model_validate(
                {"option": options.lines[n], **table.loc[n, _LINE_COLUMNS].to_dict()}
            )
            for n in result.selected
        ]
        return RunOptimizerOutput(
            candidate_set_id=stored.candidate_set_id,
            status=result.status,
            objective=result.objective,
            lines=lines,
            total_promo_cost=sum(line.promo_cost for line in lines),
            marketing_budget=request.marketing_budget,
            blended_margin=blended_margin(
                [line.revenue for line in lines], [line.gross_profit for line in lines]
            ),
            min_margin=max(request.min_margin or 0.0, policy.margin_floor),
            pairwise_cannibalisation=result.pairwise_cannibalisation,
            candidate_options=len(options.lines),
            eligible_options=result.eligible,
            pairs=result.pairs,
        )

    return Tool(
        name="run_optimizer",
        description=DESCRIPTION,
        input_type=RunOptimizerInput,
        output_type=RunOptimizerOutput,
        handler=run_optimizer,
    )
