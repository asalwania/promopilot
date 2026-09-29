"""A SKU's substitutes and complements over HTTP (SPEC §10, ADR 0033).

It answers from the same lookup as the `get_relations` tool, so the UI and the planner see
the same relations: the live relations model, fitted on the live demand model.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from promopilot.agents.tools import ToolCallError
from promopilot.agents.tools.get_relations import (
    ProductCatalogue,
    RelationsSource,
    lookup_relations,
)
from promopilot.api.schemas import QUERY_MAX_CHARS, RelationsResponse


class RelationsService:
    def __init__(self, models: RelationsSource, catalogue: ProductCatalogue) -> None:
        self._models = models
        self._catalogue = catalogue

    async def of(self, sku_id: str) -> RelationsResponse:
        """Raises `ToolCallError`: model_unavailable, or invalid_input for an unknown SKU."""
        found = await lookup_relations(self._models, self._catalogue, [sku_id])
        [relations] = found.relations
        return RelationsResponse(
            model=found.model,
            sku_id=relations.sku_id,
            substitutes=relations.substitutes,
            complements=relations.complements,
        )


def relations_router(relations: RelationsService) -> APIRouter:
    router = APIRouter(prefix="/api/relations", tags=["relations"])

    @router.get(
        "/{sku_id}",
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "No such SKU"},
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": "No relations model fitted on the live demand model"
            },
        },
    )
    async def get_relations(
        sku_id: Annotated[str, Path(max_length=QUERY_MAX_CHARS)],
    ) -> RelationsResponse:
        try:
            return await relations.of(sku_id)
        except ToolCallError as failure:
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if failure.error.code == "model_unavailable"
                else status.HTTP_404_NOT_FOUND
            )
            raise HTTPException(code, failure.error.message) from failure

    return router
