"""Reading a brief into a planning request: the Context node's step (E3, ADR 0046)."""

from typing import Protocol

import pandas as pd

from promopilot.agents.context import read_brief
from promopilot.domain import PlanningRequest
from promopilot.llm import LLMProvider


class BriefData(Protocol):
    """The as-of-week data that reading a brief needs (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...
    async def default_as_of_week(self) -> int: ...


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
