"""`get_holidays`: the festival calendar for regions over a window after the as-of week.

Holidays are known in advance, so the calendar is the one future the tools may show; the
window must still lie after the as-of week, where planning happens (ADR 0008, ADR 0032).
"""

from datetime import date
from typing import Protocol, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.domain import Region, Week

DESCRIPTION = (
    "List the holidays per region and week in a window of weeks after the as-of week: the "
    "holiday's name, the week's start date, its intensity (0 to 1: the festival week at the "
    "festival's full strength, the week before it at a lower lead-in level) and whether it "
    "is national (celebrated in every region) or regional."
)


class CalendarSource(Protocol):
    """The reads this tool makes (`promopilot.data.RetailData`)."""

    async def calendar(self) -> pd.DataFrame: ...


class GetHolidaysInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regions: list[Region] | None = Field(default=None, description="Omit for every region.")
    start_week: Week = Field(description="First week id of the window, after the as-of week.")
    end_week: Week = Field(description="Last week id of the window, inclusive.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_week < self.start_week:
            raise ValueError("the window cannot end before it starts")
        return self


class HolidayWeek(BaseModel):
    model_config = ConfigDict(frozen=True)

    holiday: str
    region: Region
    week_id: int
    week_start: date
    intensity: float
    national: bool


class GetHolidaysOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of_week: int
    holidays: list[HolidayWeek]


def get_holidays_tool(
    data: CalendarSource, as_of_week: AsOfWeekSource
) -> Tool[GetHolidaysInput, GetHolidaysOutput]:
    async def get_holidays(arguments: GetHolidaysInput) -> GetHolidaysOutput:
        week = await current_as_of_week(as_of_week)
        if arguments.start_week <= week:
            raise ToolCallError(
                "invalid_input", f"the window must start after the as-of week {week}"
            )
        calendar = await data.calendar()
        last = int(calendar["week_id"].max())
        if arguments.end_week > last:
            raise ToolCallError("invalid_input", f"the calendar ends at week {last}")
        holidays = calendar.dropna(subset=["holiday_name"])
        all_regions = set(calendar["region"])
        national = {
            str(name)
            for name, rows in holidays.groupby("holiday_name")
            if set(rows["region"]) == all_regions
        }
        regions = [r.value for r in arguments.regions] if arguments.regions else list(all_regions)
        window = holidays[
            holidays["week_id"].between(arguments.start_week, arguments.end_week)
            & holidays["region"].isin(regions)
        ]
        rank = {region.value: n for n, region in enumerate(Region)}
        window = window.assign(
            rank=window["region"].map(rank),
            holiday=window["holiday_name"],
            intensity=window["holiday_intensity"],
            national=window["holiday_name"].isin(national),
        ).sort_values(["week_id", "rank"])
        return GetHolidaysOutput(
            as_of_week=week,
            holidays=[HolidayWeek.model_validate(row) for row in window.to_dict("records")],
        )

    return Tool(
        name="get_holidays",
        description=DESCRIPTION,
        input_type=GetHolidaysInput,
        output_type=GetHolidaysOutput,
        handler=get_holidays,
    )
