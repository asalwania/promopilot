"""One planning session run: brief to planning request to plan revision 1 (E3, E6)."""

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from promopilot.agents.context import read_brief
from promopilot.domain import PlanningRequest, PlanRevision
from promopilot.llm import LLMProvider


class BriefData(Protocol):
    """The as-of-week data that reading a brief needs (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...
    async def default_as_of_week(self) -> int: ...


class Planner(Protocol):
    """Plans a planning request (`promopilot.agents.OptimisingPlanner`)."""

    async def plan(self, request: PlanningRequest) -> PlanRevision: ...


@dataclass(frozen=True)
class PlanningResult:
    request: PlanningRequest
    revision: PlanRevision


async def read_planning_request(brief: str, llm: LLMProvider, data: BriefData) -> PlanningRequest:
    """Read the brief into a planning request at the default as-of week.

    Raises `BriefError` when the brief cannot become a planning request and `LLMError` when
    the LLM fails.
    """
    products = await data.products()
    return await read_brief(
        brief,
        llm,
        as_of_week=await data.default_as_of_week(),
        calendar=await data.calendar(),
        categories=sorted(products["category"].unique()),
    )


async def plan_session(
    brief: str, llm: LLMProvider, data: BriefData, planner: Planner
) -> PlanningResult:
    """Read the brief into a planning request, then plan it.

    Raises `BriefError`, `LLMError`, or `PlanningError` when the request cannot be planned.
    """
    request = await read_planning_request(brief, llm, data)
    return PlanningResult(request, await planner.plan(request))
