"""`compare_mechanisms`: each mechanism's best promo option for one SKU in one region (F-02).

The tool generates that SKU and region's promo options for the planning request, the way
`generate_candidates` does for the whole scope, then compares the mechanisms on them
(ADR 0035, ADR 0041). It stands alone: the planner can call it before or without a candidate
set. Every number comes from the demand model's expected outcomes, with cannibalisation, halo
and clearance value; the LLM computes none.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.as_of import AsOfWeekSource
from promopilot.agents.tools.estimate_demand import DemandModelSource, ModelVersion
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.option_context import OptionDataSource, load_option_context
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import CompanyPolicy, MechanismOutcome, PlanningRequest, Region
from promopilot.mechanisms import ComparisonContext, compare
from promopilot.optimizer import generate_options

DESCRIPTION = (
    "Compare promotion mechanisms (PCT_OFF, BOGO, FIXED_PRICE, and BUNDLE when the SKU has a "
    "detected complement) for one SKU in one region of the planning request. For each "
    "mechanism it finds the option with the highest value (incremental profit - "
    "cannibalisation + halo + clearance value) over every depth, duration, start week inside "
    "the promo window and target segment that keeps the per-line rules (maximum discount, "
    "not below unit cost unless overstocked, P90 units within available stock). Returns, "
    "best first, each mechanism's option with its effective price, expected units, revenue, "
    "gross profit, margin, promo cost, incremental profit, cannibalisation, halo, clearance "
    "value and value; a BUNDLE names its partner and basket lift. A mechanism whose every "
    "option breaks a rule is listed last with the rules it breaks."
)


class CompareMechanismsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: PlanningRequest
    sku_id: str = Field(description="A SKU in the request's scope.")
    region: Region = Field(description="A region in the request's scope.")


class CompareMechanismsOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    demand_model: ModelVersion
    relations_model: ModelVersion
    as_of_week: int
    sku_id: str
    region: Region
    outcomes: list[MechanismOutcome] = Field(
        description="Mechanisms with an option, highest value first, then those without."
    )


def compare_mechanisms_tool(
    demand_models: DemandModelSource,
    relations_models: RelationsSource,
    data: OptionDataSource,
    as_of_week: AsOfWeekSource,
    *,
    policy: CompanyPolicy,
) -> Tool[CompareMechanismsInput, CompareMechanismsOutput]:
    async def compare_mechanisms(arguments: CompareMechanismsInput) -> CompareMechanismsOutput:
        request, region = arguments.request, arguments.region
        if region not in request.scope.regions:
            raise ToolCallError(
                "invalid_input", f"{region.value} is not in the planning request's scope"
            )
        loaded = await load_option_context(
            request, demand_models, relations_models, data, as_of_week, policy
        )
        context = loaded.context
        narrowed = request.model_copy(
            update={"scope": request.scope.model_copy(update={"regions": (region,)})}
        )
        try:
            # Prediction is CPU-bound: keep the event loop free (ADR 0025).
            options = await asyncio.to_thread(
                generate_options, narrowed, context, sku_ids=[arguments.sku_id]
            )
        except ValueError as error:
            raise ToolCallError("invalid_input", str(error)) from error
        outcomes = compare(
            arguments.sku_id,
            region,
            ComparisonContext(
                options=options, relations=context.relations, products=context.products
            ),
        )
        return CompareMechanismsOutput(
            demand_model=loaded.demand_model,
            relations_model=loaded.relations_model,
            as_of_week=loaded.as_of_week,
            sku_id=arguments.sku_id,
            region=region,
            outcomes=list(outcomes),
        )

    return Tool(
        name="compare_mechanisms",
        description=DESCRIPTION,
        input_type=CompareMechanismsInput,
        output_type=CompareMechanismsOutput,
        handler=compare_mechanisms,
    )
