"""`get_competitor_gaps`: competitor price index, gap and KVI undercut per SKU x region (F-08).

The as-of week is bound when the tool is built, as an async source, so the LLM can never move
the clock (ADR 0008, ADR 0032). Company policy is bound too; the LLM never sets the threshold.
"""

from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.competitors import CompetitorData, CompetitorGaps, read_competitor_gaps
from promopilot.domain import CompanyPolicy, Region

DESCRIPTION = (
    "Compare our base prices with the competitor's latest prices before the as-of week, per "
    "SKU and region, widest gap first. cpi is competitor price ÷ our base price; gap is 1 "
    "minus cpi, positive when the competitor is cheaper. undercut marks a KVI whose cpi is "
    "below 1 minus the company-policy undercut threshold. Filter by regions, categories, SKU "
    "ids or KVIs only; omit a filter to include everything."
)


class GetCompetitorGapsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regions: list[Region] | None = Field(default=None, min_length=1)
    categories: list[str] | None = Field(default=None, min_length=1)
    sku_ids: list[str] | None = Field(default=None, min_length=1)
    kvi_only: bool = False


def get_competitor_gaps_tool(
    data: CompetitorData, as_of_week: AsOfWeekSource, *, policy: CompanyPolicy
) -> Tool[GetCompetitorGapsInput, CompetitorGaps]:
    async def get_competitor_gaps(arguments: GetCompetitorGapsInput) -> CompetitorGaps:
        week = await current_as_of_week(as_of_week)
        try:
            return await read_competitor_gaps(
                data,
                as_of_week=week,
                policy=policy,
                regions=arguments.regions,
                categories=arguments.categories,
                sku_ids=arguments.sku_ids,
                kvi_only=arguments.kvi_only,
            )
        except ValueError as error:
            raise ToolCallError("invalid_input", str(error)) from error

    return Tool(
        name="get_competitor_gaps",
        description=DESCRIPTION,
        input_type=GetCompetitorGapsInput,
        output_type=CompetitorGaps,
        handler=get_competitor_gaps,
    )
