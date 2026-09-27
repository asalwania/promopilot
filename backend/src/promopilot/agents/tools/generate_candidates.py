"""`generate_candidates`: enumerate, prune and predict the promo options of a planning request.

Tens of thousands of options never reach the LLM. The tool keeps the full set in the
in-process `CandidateStore` and returns a summary: counts, pruned counts per reason, counts
per region and mechanism, the top options by value, and the candidate set's id, which
`run_optimizer` takes (ADR 0035, ADR 0036). The latest demand model and the live relations model
are resolved on every call, and the as-of week is bound when the tool is built (ADR 0025,
ADR 0032); the planning request must be for that week.
"""

import asyncio
from uuid import UUID

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.as_of import AsOfWeekSource
from promopilot.agents.tools.estimate_demand import DemandModelSource, ModelVersion
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.option_context import (
    LoadedOptionContext,
    OptionDataSource,
    load_option_context,
)
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    Region,
    TargetSegment,
)
from promopilot.optimizer import (
    CandidateStore,
    FittedOptionFacts,
    PromoOptions,
    PruneReason,
    generate_options,
)

MAX_TOP = 20

DESCRIPTION = (
    "Generate every promo option for the planning request: each in-scope SKU and region, "
    "mechanism, depth, duration, start week inside the promo window, and target segment "
    "(one segment or All customers); a BUNDLE pairs a SKU with a detected complement. "
    "Options deeper than the company-policy maximum discount, below unit cost (unless "
    "overstocked), or whose P90 units exceed available stock are pruned. The rest are "
    "predicted, with cannibalisation, halo and clearance value. Returns counts, pruned "
    "counts per reason, counts per region and mechanism, the top options by value, and a "
    "candidate_set_id to pass to the optimiser. Narrow by mechanisms, target segments or "
    "SKU ids to generate fewer."
)


class GenerateCandidatesInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: PlanningRequest
    mechanisms: list[Mechanism] | None = Field(default=None, description="Omit for all four.")
    target_segments: list[TargetSegment] | None = Field(
        default=None, description="Omit for every segment and All customers."
    )
    sku_ids: list[str] | None = Field(
        default=None, description="Only these SKUs of the request's scope; omit for all."
    )


class PrunedCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: PruneReason
    count: int


class RegionMechanismCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: Region
    mechanism: Mechanism
    count: int


class CandidateOption(BaseModel):
    """One kept option's headline numbers (rupees, units over its promo weeks)."""

    model_config = ConfigDict(frozen=True)

    option: PlanLine
    units: float
    p90_units: float
    available_stock: float
    promo_cost: float
    incremental_profit: float
    cannibalised_profit: float
    halo_profit: float
    clearance_value: float
    value: float = Field(
        description="incremental_profit - cannibalised_profit + halo_profit + clearance_value"
    )


class GenerateCandidatesOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_set_id: UUID
    demand_model: ModelVersion
    relations_model: ModelVersion
    as_of_week: int
    enumerated: int
    kept: int
    pruned: list[PrunedCount]
    by_region_and_mechanism: list[RegionMechanismCount]
    top: list[CandidateOption] = Field(description=f"Up to {MAX_TOP} options, best value first.")


def generate_candidates_tool(
    demand_models: DemandModelSource,
    relations_models: RelationsSource,
    data: OptionDataSource,
    as_of_week: AsOfWeekSource,
    *,
    policy: CompanyPolicy,
    store: CandidateStore,
) -> Tool[GenerateCandidatesInput, GenerateCandidatesOutput]:
    async def generate_candidates(arguments: GenerateCandidatesInput) -> GenerateCandidatesOutput:
        request = arguments.request
        loaded = await load_option_context(
            request, demand_models, relations_models, data, as_of_week, policy
        )
        context = loaded.context
        try:
            # Prediction is CPU-bound: keep the event loop free (ADR 0025).
            options = await asyncio.to_thread(
                generate_options,
                request,
                context,
                mechanisms=arguments.mechanisms,
                target_segments=arguments.target_segments,
                sku_ids=arguments.sku_ids,
            )
        except ValueError as error:
            raise ToolCallError("invalid_input", str(error)) from error
        stored = store.put(request, options, FittedOptionFacts(context))
        return _summary(stored.candidate_set_id, options, loaded)

    return Tool(
        name="generate_candidates",
        description=DESCRIPTION,
        input_type=GenerateCandidatesInput,
        output_type=GenerateCandidatesOutput,
        handler=generate_candidates,
    )


def _summary(
    candidate_set_id: UUID, options: PromoOptions, loaded: LoadedOptionContext
) -> GenerateCandidatesOutput:
    table = options.table
    counts = pd.Series(
        [(line.region, line.mechanism) for line in options.lines], dtype=object
    ).value_counts()
    rank = {
        (region, mechanism): (r, m)
        for r, region in enumerate(Region)
        for m, mechanism in enumerate(Mechanism)
    }
    best = table["value"].sort_values(ascending=False, kind="stable").index[:MAX_TOP]
    return GenerateCandidatesOutput(
        candidate_set_id=candidate_set_id,
        demand_model=loaded.demand_model,
        relations_model=loaded.relations_model,
        as_of_week=loaded.as_of_week,
        enumerated=options.enumerated,
        kept=len(options.lines),
        pruned=[
            PrunedCount(reason=reason, count=count) for reason, count in options.pruned.items()
        ],
        by_region_and_mechanism=[
            RegionMechanismCount(region=key[0], mechanism=key[1], count=int(counts[key]))
            for key in sorted(counts.index, key=rank.__getitem__)
        ],
        top=[
            CandidateOption.model_validate(
                {"option": options.lines[n], **table.loc[n, _TOP_COLUMNS].to_dict()}
            )
            for n in best
        ],
    )


_TOP_COLUMNS = [name for name in CandidateOption.model_fields if name != "option"]
