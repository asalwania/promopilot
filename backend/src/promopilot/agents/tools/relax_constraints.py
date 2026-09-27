"""`relax_constraints`: the smallest change to an infeasible request's brief constraints.

The planner passes the `candidate_set_id` that `generate_candidates` returned, as for
`run_optimizer`. The optimiser re-solves with slack on the brief's constraints only (the
marketing budget and regional caps, the minimum margin down to the margin floor, a tighter
promoted-SKU cap, a KVI tolerance the brief turned on, the clearance targets) and reports the
smallest change to each (ADR 0044). Company policy is never relaxed. Every number comes from
the stored options and the solver; the LLM decides only whether to propose it.
"""

import asyncio
from dataclasses import replace
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import (
    BindingConstraint,
    ClearanceShortfall,
    CompanyPolicy,
    PolicyFinding,
    Relaxation,
    SolveStatus,
)
from promopilot.optimizer import CandidateStore, SolverSettings, solve

DESCRIPTION = (
    "For a candidate set made by generate_candidates, say whether its request is feasible and, "
    "if no plan can reach every clearance target within the request's other constraints, the "
    "smallest change to the request's own constraints that makes it feasible: a higher "
    "marketing budget or regional budget cap, a lower minimum margin (never below the "
    "company-policy margin floor), a looser promoted-SKU cap (never above policy's), the KVI "
    "price tolerance turned off (only when the request turned it on), or a lower or dropped "
    "clearance target. The change is the least sum of each change as a share of the "
    "request's value. Company policy is never relaxed: policy_binds says when no change to the "
    "budget, caps, margin or tolerance alone would reach the targets, so a target must come "
    "down, and policy_allows gives the most sell-through policy allows. Returns the solver "
    "status (INFEASIBLE, OPTIMAL, or FEASIBLE when the time limit ran out before either was "
    "proven), the relaxation (null when the request is feasible), the constraints that make "
    "it infeasible, and the clearance shortfalls of the closest plan. A candidate_set_id that "
    "is no longer stored must be regenerated."
)


class RelaxConstraintsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_set_id: UUID = Field(description="From generate_candidates.")


class RelaxConstraintsOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_set_id: UUID
    status: SolveStatus
    relaxation: Relaxation | None = Field(
        description="The smallest change to the request's constraints that makes it feasible; "
        "null when it is feasible. proven is false when time ran out first."
    )
    binding_constraints: list[BindingConstraint] = Field(
        description="For an infeasible request: the clearance targets missed and each "
        "constraint the relaxation changes, at the request's values."
    )
    clearance_shortfalls: list[ClearanceShortfall] = Field(
        description="Clearance targets the closest plan misses, and by how much."
    )
    policy_findings: list[PolicyFinding] = Field(
        description="Request values that would have loosened company policy; policy was kept."
    )


def relax_constraints_tool(
    store: CandidateStore,
    *,
    policy: CompanyPolicy,
    settings: SolverSettings,
    seed: int,
) -> Tool[RelaxConstraintsInput, RelaxConstraintsOutput]:
    # The binding analysis of a feasible plan is run_optimizer's job, not this tool's.
    relaxing = replace(settings, binding_time_limit_seconds=0)

    async def relax_constraints(arguments: RelaxConstraintsInput) -> RelaxConstraintsOutput:
        stored = store.get(arguments.candidate_set_id)
        if stored is None:
            raise ToolCallError(
                "invalid_input",
                f"no candidate set {arguments.candidate_set_id} is stored (it may have been "
                "dropped or made before a restart); call generate_candidates again",
            )
        # Solving is CPU-bound: keep the event loop free (ADR 0025).
        result = await asyncio.to_thread(
            solve,
            stored.request,
            stored.options,
            stored.facts,
            policy,
            settings=relaxing,
            seed=seed,
        )
        infeasible = result.status is SolveStatus.INFEASIBLE
        return RelaxConstraintsOutput(
            candidate_set_id=stored.candidate_set_id,
            status=result.status,
            relaxation=result.relaxation,
            binding_constraints=list(result.binding_constraints) if infeasible else [],
            clearance_shortfalls=list(result.clearance_shortfalls),
            policy_findings=list(result.policy_findings),
        )

    return Tool(
        name="relax_constraints",
        description=DESCRIPTION,
        input_type=RelaxConstraintsInput,
        output_type=RelaxConstraintsOutput,
        handler=relax_constraints,
    )
