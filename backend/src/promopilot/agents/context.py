"""The Context agent: brief → planning request with its assumptions, or clarification
questions (SPEC §9.6, AG-01, AG-02, ADR 0048).

The LLM only extracts: the brief's own phrases for its scope, holiday and clearance SKUs, and
the numbers it states. `promopilot.agents.assumptions` then resolves and checks every value
against the data with no LLM, so the same reading always gives the same request, assumptions
and questions.
"""

import json
from collections.abc import Sequence
from importlib.resources import files
from string import Template
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import Clarification, Region
from promopilot.llm import LLMProvider, Message

WEEK_TABLE_WEEKS = 26
"""How far past the as-of week the promo window may be chosen."""


class BriefError(Exception):
    """The brief cannot become a valid planning request (a field is missing or invalid)."""


def _every_field_required(schema: dict[str, Any]) -> None:
    # Structured outputs need every property required; fields added after E3 keep a Python
    # default only so code that builds a reading by hand need not name them. The LLM is never
    # shown those defaults.
    properties = schema.get("properties", {})
    for field in properties.values():
        field.pop("default", None)
    schema["required"] = list(properties)


class ClearanceAsk(BaseModel):
    """One clearance the brief asks for: the SKUs in its words and the sell-through it wants."""

    model_config = ConfigDict(json_schema_extra=_every_field_required)

    products: str = Field(
        description="The brief's own words naming the SKUs to clear, e.g. '400g namkeen packs'."
    )
    sell_through: float | None = Field(
        description="The share of that stock to sell, as a fraction (60% is 0.6); null if unsaid."
    )


class RegionalCap(BaseModel):
    """A cap the brief puts on the promo cost spent in one region."""

    model_config = ConfigDict(json_schema_extra=_every_field_required)

    region: Region
    cap: float = Field(description="The cap in rupees (₹90k is 90000).")


class BriefReading(BaseModel):
    """What the LLM extracts from a brief. Null means the brief does not say."""

    model_config = ConfigDict(json_schema_extra=_every_field_required)

    regions: list[Region] | None = Field(description="Regions the brief covers.")
    regions_phrase: str | None = Field(
        default=None, description="The brief's own words naming the regions, verbatim."
    )
    categories: list[str] | None = Field(description="Product categories the brief covers.")
    categories_phrase: str | None = Field(
        default=None, description="The brief's own words naming the categories, verbatim."
    )
    sku_ids: list[str] | None = Field(description="SKU ids the brief names explicitly.")
    promo_start_week: int | None = Field(description="First promo week id, from the table.")
    promo_end_week: int | None = Field(description="Last promo week id, from the table.")
    holiday: str | None = Field(
        default=None, description="The holiday or festival the brief times the promotion around."
    )
    marketing_budget: float | None = Field(description="Marketing budget in rupees.")
    min_margin: float | None = Field(description="Minimum margin as a fraction.")
    clearance: list[ClearanceAsk] | None = Field(
        default=None, description="Stock the brief asks to clear."
    )
    regional_budget_caps: list[RegionalCap] | None = Field(
        default=None, description="Budget caps the brief sets for single regions."
    )
    kvi_price_tolerance: float | None = Field(
        default=None,
        description="How far above the competitor a KVI promo price may sit, as a fraction.",
    )
    max_promoted_skus_per_category_per_region: int | None = Field(
        default=None, description="The most SKUs to promote per category in a region."
    )
    objective_asked: Literal["profit", "revenue", "volume"] | None = Field(
        default=None, description="What the brief asks the plan to maximise, if it says."
    )
    segment_phrase: str | None = Field(
        default=None, description="The brief's own words naming customers to target, verbatim."
    )


def context_prompt() -> Template:
    return Template((files("promopilot.agents") / "prompts" / "context.md").read_text("utf-8"))


def amendments_prompt() -> str:
    """The rules for reading amendments, added to the system prompt only when there are any,
    so a brief without them is asked exactly as before (ADR 0052)."""
    return (files("promopilot.agents") / "prompts" / "context_amendments.md").read_text("utf-8")


def week_table(calendar: pd.DataFrame, as_of_week: int) -> pd.DataFrame:
    """The calendar rows a promo window may be chosen from: the weeks after the as-of week."""
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


def context_messages(
    brief: str,
    *,
    as_of_week: int,
    as_of_date: str,
    table: pd.DataFrame,
    regions: Sequence[str],
    categories: Sequence[str],
    clarifications: Sequence[Clarification] = (),
    amendments: Sequence[str] = (),
) -> list[Message]:
    """The system prompt and the user's words, which travel only as quoted JSON data."""
    system = context_prompt().substitute(
        regions=", ".join(regions),
        categories=", ".join(categories),
        as_of_week=as_of_week,
        as_of_date=as_of_date,
        week_table=_week_table_text(table),
    )
    if amendments:
        system = f"{system}{amendments_prompt()}"
    # The brief travels as a JSON string: quoted data, never instructions (SPEC §9.6).
    user = f"Brief (a JSON string written by the user):\n{json.dumps(brief, ensure_ascii=False)}"
    if clarifications:
        answered = [{"question": c.question.question, "answer": c.answer} for c in clarifications]
        user += (
            "\n\nThe user's answers to your clarification questions (JSON, the answers written "
            f"by the user):\n{json.dumps(answered, ensure_ascii=False)}"
        )
    if amendments:
        user += (
            "\n\nAmendments to the brief, oldest first (JSON strings written by the user):\n"
            f"{json.dumps(list(amendments), ensure_ascii=False)}"
        )
    return [Message(role="system", content=system), Message(role="user", content=user)]


async def read_brief(llm: LLMProvider, messages: Sequence[Message]) -> BriefReading:
    """Ask the LLM for its reading of the brief."""
    return await llm.complete_structured(BriefReading, messages)
