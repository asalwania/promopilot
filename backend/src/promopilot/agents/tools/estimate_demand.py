"""`estimate_demand`: the demand model's predictions for a batch of promo options (SPEC §9.1).

The latest registered demand model is resolved on every call, so a retrain is picked up
without rebuilding the tool (ADR 0025). Company policy is bound when the tool is built; the
LLM never sets it. The numbers are `DemandModel.predict`'s, unrounded.
"""

import asyncio
from typing import Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import CompanyPolicy, PlanLine, Region, Segment
from promopilot.models.demand import DemandModel, PredictionContext
from promopilot.models.registry import RegisteredModel

MAX_OPTIONS = 200

DESCRIPTION = (
    "Predict what each promo option would do if it ran alone: units sold in its region over "
    "the promo weeks (mean and standard deviation), the no-promotion baseline, the "
    "pull-forward dip in the four weeks after, incremental units net of that dip, revenue, "
    "gross profit, margin, promo cost and incremental profit in rupees, plus units per "
    "customer segment. Options must start on or after the model's as-of week. Competitor "
    "prices default to the last ones known; override them per region and SKU to test a "
    "competitor move. Cannibalisation and halo on other SKUs are not included."
)


class DemandModelSource(Protocol):
    """The latest registered demand model, or None (`promopilot.models.registry.LatestModel`)."""

    async def get(self) -> tuple[RegisteredModel, DemandModel] | None: ...


class CompetitorPrice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    region: Region
    sku_id: str
    price: float = Field(gt=0, description="The competitor's shelf price in rupees.")


class EstimateDemandInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    options: list[PlanLine] = Field(min_length=1, max_length=MAX_OPTIONS)
    competitor_prices: list[CompetitorPrice] = Field(
        default_factory=list,
        description="Competitor price overrides over the promo; others are the last known.",
    )

    @model_validator(mode="after")
    def _one_price_per_region_and_sku(self) -> Self:
        keys = [(price.region, price.sku_id) for price in self.competitor_prices]
        if len(keys) != len(set(keys)):
            raise ValueError("at most one competitor price per region and SKU")
        return self


class ModelVersion(BaseModel):
    """The registered model that produced the numbers, so a plan can be traced to it."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())

    model_id: UUID
    version: int
    as_of_week: int


class SegmentEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    segment: Segment
    units: float
    units_std: float
    baseline_units: float


class OptionEstimate(BaseModel):
    """One option's predicted outcomes, summed over its region (field meanings: ADR 0024)."""

    model_config = ConfigDict(frozen=True)

    option: PlanLine
    units: float
    units_std: float
    baseline_units: float
    pull_forward_units: float
    incremental_units: float
    revenue: float
    gross_profit: float
    margin: float
    promo_cost: float
    incremental_profit: float
    segments: list[SegmentEstimate]


class EstimateDemandOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: ModelVersion
    estimates: list[OptionEstimate]


def estimate_demand_tool(
    models: DemandModelSource, *, policy: CompanyPolicy
) -> Tool[EstimateDemandInput, EstimateDemandOutput]:
    async def estimate_demand(arguments: EstimateDemandInput) -> EstimateDemandOutput:
        loaded = await models.get()
        if loaded is None:
            raise ToolCallError("model_unavailable", "no demand model is registered yet")
        entry, model = loaded
        context = PredictionContext(
            policy=policy,
            competitor_prices={
                (price.region, price.sku_id): price.price for price in arguments.competitor_prices
            },
        )
        try:
            # Prediction is CPU-bound (~0.4 s per 100 options): keep the event loop free.
            prediction = await asyncio.to_thread(model.predict, arguments.options, context)
        except ValueError as error:
            raise ToolCallError("invalid_input", str(error)) from error
        segments = prediction.segments.groupby("option")
        return EstimateDemandOutput(
            model=ModelVersion(
                model_id=entry.model_id, version=entry.version, as_of_week=model.as_of_week
            ),
            estimates=[
                OptionEstimate.model_validate(
                    {
                        "option": line,
                        **row,
                        "segments": segments.get_group(n).to_dict("records"),
                    }
                )
                for n, (line, row) in enumerate(
                    zip(arguments.options, prediction.options.to_dict("records"), strict=True)
                )
            ],
        )

    return Tool(
        name="estimate_demand",
        description=DESCRIPTION,
        input_type=EstimateDemandInput,
        output_type=EstimateDemandOutput,
        handler=estimate_demand,
    )
