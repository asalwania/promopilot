"""Reading a brief into a planning request: the Context node's step (ADR 0046, ADR 0048), by
rules when the LLM is unavailable (ADR 0053)."""

from collections.abc import Sequence
from typing import Protocol

import pandas as pd
import structlog

from promopilot.agents.amendments import apply_accepted
from promopilot.agents.assumptions import (
    ContextReading,
    ContextWorld,
    interpret,
    missing_fields_message,
)
from promopilot.agents.context import BriefError, context_messages, read_brief, week_table
from promopilot.agents.fallback import read_by_rules
from promopilot.agents.state import AcceptedRelaxation, DegradedReason
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.domain import Clarification, CompanyPolicy, PlanningRequest
from promopilot.llm import CassetteMissError, LLMError, LLMProvider

log = structlog.get_logger(__name__)


class BriefData(Protocol):
    """The as-of-week data that reading a brief needs (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...
    async def default_as_of_week(self) -> int: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...
    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame: ...


async def read_context(
    brief: str,
    llm: LLMProvider,
    data: BriefData,
    *,
    policy: CompanyPolicy,
    clarifications: Sequence[Clarification] = (),
    amendments: Sequence[str] = (),
    accepted: Sequence[AcceptedRelaxation] = (),
    fallback: bool = False,
) -> ContextReading:
    """Read the brief, the answers so far and any amendments at the default as-of week: a
    planning request with its assumptions, or the questions to ask first (ADR 0048). Each
    accepted relaxation is then applied in code; the LLM never reads it (ADR 0083).

    Raises `BriefError` when the reading cannot form a planning request and `LLMError` when
    the LLM fails, unless `fallback`: then the brief is read by rules instead, a cassette miss
    included, and the reading says why (ADR 0053).
    """
    as_of_week = await data.default_as_of_week()
    products = await data.products()
    calendar = await data.calendar()
    as_of_rows = calendar[calendar["week_id"] == as_of_week]["week_start"]
    as_of_date = str(as_of_rows.iloc[0]) if len(as_of_rows) else "unknown"
    messages = context_messages(
        brief,
        as_of_week=as_of_week,
        as_of_date=as_of_date,
        table=week_table(calendar, as_of_week),
        regions=sorted(calendar["region"].unique()),
        categories=sorted(products["category"].unique()),
        clarifications=clarifications,
        amendments=amendments,
    )
    reading, degraded = None, None
    try:
        reading = await read_brief(llm, messages)
    except LLMError as error:
        if not fallback:
            raise
        degraded = (
            DegradedReason.CASSETTE_MISSING
            if isinstance(error, CassetteMissError)
            else DegradedReason.LLM_UNAVAILABLE
        )
        log.warning("context_fallback", reason=degraded.value, error=str(error))
    try:
        snapshot = await data.inventory(as_of_week)
    except LookupError:
        stock = None  # no snapshot yet: the planner reports it; the overstock list is skipped
    else:
        stock = pooled_stock(snapshot, await data.stores(), policy)
    world = ContextWorld(
        as_of_week=as_of_week,
        as_of_date=as_of_date,
        products=products,
        calendar=calendar,
        stock=stock,
        competitor_prices=await data.latest_competitor_prices(as_of_week),
        policy=policy,
    )
    if reading is None:
        read = read_by_rules(
            brief,
            world,
            clarifications=clarifications,
            amendments=amendments,
            degraded=degraded or DegradedReason.LLM_UNAVAILABLE,
        )
    else:
        read = interpret(reading, world)
    return apply_accepted(read, accepted, policy)


async def read_planning_request(
    brief: str, llm: LLMProvider, data: BriefData, policy: CompanyPolicy | None = None
) -> PlanningRequest:
    """Read a brief that needs no clarification into a planning request.

    Raises `BriefError` when it needs one (naming what is missing) or is invalid, and
    `LLMError` when the LLM fails.
    """
    reading = await read_context(brief, llm, data, policy=policy or CompanyPolicy())
    if reading.request is None:
        raise BriefError(missing_fields_message(reading.questions))
    return reading.request
