"""One planning session run, brief to plan revision 1 (E3 walking skeleton)."""

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from promopilot.agents.context import read_brief
from promopilot.agents.naive_planner import naive_plan, recent_sales_since
from promopilot.domain import CompanyPolicy, PlanningRequest, PlanRevision
from promopilot.llm import LLMProvider


class PlanningData(Protocol):
    """The as-of-week retail data a planning session reads (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...
    async def sales_history(
        self, as_of_week: int, *, since_week: int | None = None
    ) -> pd.DataFrame: ...
    async def default_as_of_week(self) -> int: ...


@dataclass(frozen=True)
class PlanningResult:
    request: PlanningRequest
    revision: PlanRevision


async def plan_session(
    brief: str,
    llm: LLMProvider,
    data: PlanningData,
    *,
    policy: CompanyPolicy | None = None,
) -> PlanningResult:
    """Read the brief into a planning request, then plan it at the default as-of week.

    Raises `BriefError` when the brief cannot become a planning request and `LLMError` when
    the LLM fails.
    """
    policy = policy or CompanyPolicy()
    as_of_week = await data.default_as_of_week()
    products = await data.products()
    request = await read_brief(
        brief,
        llm,
        as_of_week=as_of_week,
        calendar=await data.calendar(),
        categories=sorted(products["category"].unique()),
    )
    recent = await data.sales_history(as_of_week, since_week=recent_sales_since(as_of_week))
    revision = naive_plan(
        request,
        products=products,
        stores=await data.stores(),
        recent_sales=recent,
        policy=policy,
    )
    return PlanningResult(request, revision)
