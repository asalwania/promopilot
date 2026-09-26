"""The minimal Context agent: brief → planning request through the LLM (SPEC §9.6, E3).

The LLM only extracts; this module validates every value it returns against the data.
Assumptions, confidence and clarification arrive in E8.
"""

import json
from collections.abc import Sequence
from importlib.resources import files
from string import Template

import pandas as pd
import pydantic
from pydantic import BaseModel, Field

from promopilot.domain import PlanningRequest, PromoWindow, Region, Scope
from promopilot.llm import LLMProvider, Message

WEEK_TABLE_WEEKS = 26
"""How far past the as-of week the promo window may be chosen."""


class BriefError(Exception):
    """The brief cannot become a valid planning request (a field is missing or invalid)."""


class BriefReading(BaseModel):
    """What the LLM extracts from a brief. Null means the brief does not say."""

    regions: list[Region] | None = Field(description="Regions the brief covers.")
    categories: list[str] | None = Field(description="Product categories the brief covers.")
    sku_ids: list[str] | None = Field(description="SKU ids the brief names explicitly.")
    promo_start_week: int | None = Field(description="First promo week id, from the table.")
    promo_end_week: int | None = Field(description="Last promo week id, from the table.")
    marketing_budget: float | None = Field(description="Marketing budget in rupees.")
    min_margin: float | None = Field(description="Minimum margin as a fraction.")


def context_prompt() -> Template:
    return Template((files("promopilot.agents") / "prompts" / "context.md").read_text("utf-8"))


def _week_table(calendar: pd.DataFrame, as_of_week: int) -> pd.DataFrame:
    ahead = calendar[
        (calendar["week_id"] > as_of_week) & (calendar["week_id"] <= as_of_week + WEEK_TABLE_WEEKS)
    ]
    return ahead.sort_values(["week_id", "region"])


def _week_table_text(table: pd.DataFrame) -> str:
    rows = []
    for week_id, week in table.groupby("week_id", sort=True):
        holidays: dict[str, list[str]] = {}
        for _, row in week.dropna(subset=["holiday_name"]).iterrows():
            holidays.setdefault(str(row["holiday_name"]), []).append(str(row["region"]))
        names = "; ".join(f"{name} ({', '.join(regions)})" for name, regions in holidays.items())
        rows.append(f"{week_id} | {week['week_start'].iloc[0]} | {names or '-'}")
    return "\n".join(rows)


def _messages(
    brief: str,
    *,
    as_of_week: int,
    as_of_date: str,
    table: pd.DataFrame,
    regions: Sequence[str],
    categories: Sequence[str],
) -> list[Message]:
    system = context_prompt().substitute(
        regions=", ".join(regions),
        categories=", ".join(categories),
        as_of_week=as_of_week,
        as_of_date=as_of_date,
        week_table=_week_table_text(table),
    )
    # The brief travels as a JSON string: quoted data, never instructions (SPEC §9.6).
    user = f"Brief (a JSON string written by the user):\n{json.dumps(brief, ensure_ascii=False)}"
    return [Message(role="system", content=system), Message(role="user", content=user)]


async def read_brief(
    brief: str,
    llm: LLMProvider,
    *,
    as_of_week: int,
    calendar: pd.DataFrame,
    categories: Sequence[str],
) -> PlanningRequest:
    """Ask the LLM to read the brief, then validate its reading into a planning request."""
    table = _week_table(calendar, as_of_week)
    regions = sorted(calendar["region"].unique())
    as_of_rows = calendar[calendar["week_id"] == as_of_week]["week_start"]
    as_of_date = str(as_of_rows.iloc[0]) if len(as_of_rows) else "unknown"
    reading = await llm.complete_structured(
        BriefReading,
        _messages(
            brief,
            as_of_week=as_of_week,
            as_of_date=as_of_date,
            table=table,
            regions=regions,
            categories=categories,
        ),
    )
    return _to_request(reading, as_of_week, set(table["week_id"]), regions, categories)


def _to_request(
    reading: BriefReading,
    as_of_week: int,
    table_weeks: set[int],
    regions: Sequence[str],
    categories: Sequence[str],
) -> PlanningRequest:
    budget, start, end = reading.marketing_budget, reading.promo_start_week, reading.promo_end_week
    in_regions, in_categories = reading.regions or [], reading.categories or []
    missing = [
        name
        for name, absent in [
            ("marketing budget", budget is None),
            ("regions", not in_regions),
            ("categories", not in_categories),
            ("promo window", start is None or end is None),
        ]
        if absent
    ]
    if missing or budget is None or start is None or end is None:
        raise BriefError(f"the brief does not state: {', '.join(missing)}")
    unknown = [r.value for r in in_regions if r.value not in regions] + [
        c for c in in_categories if c not in categories
    ]
    if unknown:
        raise BriefError(f"the brief names regions or categories not in the data: {unknown}")
    if start not in table_weeks or end not in table_weeks:
        raise BriefError(f"promo window weeks {start}-{end} are not in the plannable week table")
    try:
        return PlanningRequest(
            as_of_week=as_of_week,
            scope=Scope(
                regions=tuple(in_regions),
                categories=tuple(in_categories),
                sku_ids=tuple(reading.sku_ids or ()),
            ),
            promo_window=PromoWindow(start_week=start, end_week=end),
            marketing_budget=budget,
            min_margin=reading.min_margin,
        )
    except pydantic.ValidationError as error:
        raise BriefError(f"the brief's reading is not a valid planning request: {error}") from error
