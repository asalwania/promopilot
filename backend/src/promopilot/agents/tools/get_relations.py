"""`get_relations`: the detected substitutes and complements of SKUs (SPEC §9.2, §9.6).

The live relations model is resolved on every call, and served only while it was fitted
on the live demand model (ADR 0033). The numbers are the model's, unrounded.
"""

import math
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.estimate_demand import ModelVersion
from promopilot.agents.tools.registry import Tool, ToolCallError
from promopilot.models.registry import RegisteredModel
from promopilot.models.relations import Relations

MAX_SKUS = 50

DESCRIPTION = (
    "List the detected substitutes and complements of each SKU. A substitute is a SKU in "
    "the same subcategory whose sales fall when this SKU's price is cut (cannibalisation): "
    "theta is the cross-price effect, with its standard error and Benjamini-Hochberg "
    "q-value, strongest first. A complement is a SKU bought with this one far more often "
    "than chance (halo): lift and support come from baskets, and theta, negative, is the "
    "cross-price effect where it could be estimated (null otherwise), highest lift first. "
    "Relations hold in every region."
)


class RelationsSource(Protocol):
    """The live relations model, or None (`promopilot.models.serving.LiveRelations`)."""

    async def get(self) -> tuple[RegisteredModel, Relations] | None: ...


class ProductCatalogue(Protocol):
    """The product table (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...


class GetRelationsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sku_ids: list[str] = Field(min_length=1, max_length=MAX_SKUS)


class Substitute(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    theta: float = Field(description="Cross-price effect: positive for a substitute.")
    std_error: float
    q_value: float


class Complement(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    lift: float = Field(description="P(both in a basket) / (P(one) x P(other)).")
    support: float = Field(description="Share of baskets holding both SKUs.")
    theta: float | None = Field(description="Cross-price effect, or null if not estimable.")
    std_error: float | None


class SkuRelations(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    substitutes: list[Substitute]
    complements: list[Complement]

    @classmethod
    def of(cls, relations: Relations, sku_id: str) -> "SkuRelations":
        return cls(
            sku_id=sku_id,
            substitutes=[
                Substitute.model_validate(row)
                for row in relations.substitutes(sku_id).to_dict("records")
            ],
            complements=[
                Complement.model_validate({key: _finite(value) for key, value in row.items()})
                for row in relations.complements(sku_id).to_dict("records")
            ],
        )


class GetRelationsOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: ModelVersion
    relations: list[SkuRelations]


async def lookup_relations(
    models: RelationsSource, catalogue: ProductCatalogue, sku_ids: list[str]
) -> GetRelationsOutput:
    """The relations of each SKU, in order; `ToolCallError` for no model or an unknown SKU."""
    loaded = await models.get()
    if loaded is None:
        raise ToolCallError(
            "model_unavailable",
            "no relations model fitted on the live demand model is registered yet",
        )
    entry, relations = loaded
    known = set((await catalogue.products())["sku_id"])
    unknown = [sku_id for sku_id in dict.fromkeys(sku_ids) if sku_id not in known]
    if unknown:
        raise ToolCallError("invalid_input", f"unknown SKU: {', '.join(unknown)}")
    return GetRelationsOutput(
        model=ModelVersion(
            model_id=entry.model_id, version=entry.version, as_of_week=relations.as_of_week
        ),
        relations=[SkuRelations.of(relations, sku_id) for sku_id in sku_ids],
    )


def get_relations_tool(
    models: RelationsSource, catalogue: ProductCatalogue
) -> Tool[GetRelationsInput, GetRelationsOutput]:
    async def get_relations(arguments: GetRelationsInput) -> GetRelationsOutput:
        return await lookup_relations(models, catalogue, arguments.sku_ids)

    return Tool(
        name="get_relations",
        description=DESCRIPTION,
        input_type=GetRelationsInput,
        output_type=GetRelationsOutput,
        handler=get_relations,
    )


def _finite(value: object) -> object:
    return None if isinstance(value, float) and math.isnan(value) else value
