"""`generate_candidates`: enumerate, prune and predict the promo options of a planning request.

Tens of thousands of options never reach the LLM. The tool keeps the full set in the
in-process `CandidateStore` and returns a summary: counts, pruned counts per reason, counts
per region and mechanism, the top options by value, and the candidate set's id, which
`run_optimizer` takes (ADR 0035, ADR 0036). The latest demand model and the live relations model
are resolved on every call, and the as-of week is bound when the tool is built (ADR 0025,
ADR 0032); the planning request must be for that week.
"""

import asyncio
from typing import Protocol
from uuid import UUID

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.catalogue_filter import in_scope
from promopilot.agents.tools.estimate_demand import DemandModelSource, ModelVersion
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    Region,
    TargetSegment,
)
from promopilot.models.registry import RegisteredModel
from promopilot.optimizer import (
    CandidateStore,
    FittedOptionFacts,
    OptionContext,
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


class CandidateDataSource(Protocol):
    """The reads this tool makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...


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
    data: CandidateDataSource,
    as_of_week: AsOfWeekSource,
    *,
    policy: CompanyPolicy,
    store: CandidateStore,
) -> Tool[GenerateCandidatesInput, GenerateCandidatesOutput]:
    async def generate_candidates(arguments: GenerateCandidatesInput) -> GenerateCandidatesOutput:
        request = arguments.request
        week = await current_as_of_week(as_of_week)
        if request.as_of_week != week:
            raise ToolCallError(
                "invalid_input",
                f"the planning request is for as-of week {request.as_of_week}, "
                f"but planning is at as-of week {week}",
            )
        demand = await demand_models.get()
        relations = await relations_models.get()
        if demand is None or relations is None:
            raise ToolCallError(
                "model_unavailable", "no demand model, or no relations model fitted on it, yet"
            )
        stores = await data.stores()
        products = await data.products()
        in_scope(
            products,
            sorted(stores["region"].unique()),
            regions=request.scope.regions,
            categories=request.scope.categories,
            sku_ids=request.scope.sku_ids or None,
        )
        try:
            snapshot = await data.inventory(week)
        except LookupError as error:
            raise ToolCallError("data_unavailable", str(error)) from error
        context = OptionContext(
            demand_model=demand[1],
            relations=relations[1],
            products=products,
            stock=pooled_stock(snapshot, stores, policy),
            policy=policy,
        )
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
        return _summary(stored.candidate_set_id, options, week, demand[0], relations[0])

    return Tool(
        name="generate_candidates",
        description=DESCRIPTION,
        input_type=GenerateCandidatesInput,
        output_type=GenerateCandidatesOutput,
        handler=generate_candidates,
    )


def _summary(
    candidate_set_id: UUID,
    options: PromoOptions,
    as_of_week: int,
    demand: RegisteredModel,
    relations: RegisteredModel,
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
        demand_model=_version(demand),
        relations_model=_version(relations),
        as_of_week=as_of_week,
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


def _version(entry: RegisteredModel) -> ModelVersion:
    return ModelVersion(model_id=entry.model_id, version=entry.version, as_of_week=entry.as_of_week)
