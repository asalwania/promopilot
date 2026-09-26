"""The model registry over HTTP: list the versions, retrain demand and relations (SF-02, ADR 0026).

`POST /api/models/retrain` holds the request open while the model fits in a worker thread,
so the API keeps serving, and answers with the new version once it is registered and live.
"""

import asyncio

from fastapi import APIRouter, HTTPException, status

from promopilot.api.schemas import ModelEntry, ModelList
from promopilot.data import RetailData
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelRegistry
from promopilot.models.relations import Relations
from promopilot.models.serving import LiveRelations
from promopilot.models.training import DEFAULT_SEED, train_models


class RetrainInProgressError(Exception):
    """A retrain is already running in this API process."""


class NoTrainingDataError(Exception):
    """No sales history is loaded to train on."""


class ModelService:
    """The registered models and the ones live in this API process."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        data: RetailData,
        live: LatestModel[DemandModel],
        live_relations: LiveRelations[Relations] | None = None,
        seed: int = DEFAULT_SEED,
    ) -> None:
        self._registry = registry
        self._data = data
        self._live = live
        self._live_relations = live_relations
        self._seed = seed
        self._retraining = asyncio.Lock()

    async def list(self) -> ModelList:
        live_ids = set()
        for source in (self._live, self._live_relations):
            loaded = None if source is None else await source.get()
            if loaded is not None:
                live_ids.add(loaded[0].model_id)
        return ModelList(
            models=[
                ModelEntry.of(entry, live=entry.model_id in live_ids)
                for entry in await self._registry.list()
            ]
        )

    async def retrain(self) -> ModelEntry:
        """Fit demand and relations on the default as-of week and seed, register both, and put
        both live (ADR 0029, ADR 0033)."""
        # No await between the check and the acquire, so two requests cannot both pass.
        if self._retraining.locked():
            raise RetrainInProgressError("a retrain is already running; try again when it finishes")
        async with self._retraining:
            try:
                as_of_week = await self._data.default_as_of_week()
            except LookupError as error:
                raise NoTrainingDataError(str(error)) from error
            trained = await train_models(
                self._data, self._registry, as_of_week=as_of_week, seed=self._seed
            )
            self._live.set((trained.demand, trained.demand_model))
            if self._live_relations is not None:
                self._live_relations.set((trained.relations, trained.relations_model))
        return ModelEntry.of(trained.demand, live=True)


def models_router(models: ModelService) -> APIRouter:
    router = APIRouter(prefix="/api/models", tags=["models"])

    @router.get("")
    async def list_models() -> ModelList:
        return await models.list()

    @router.post(
        "/retrain",
        status_code=status.HTTP_201_CREATED,
        responses={status.HTTP_409_CONFLICT: {"description": "A retrain is running or no data"}},
    )
    async def retrain() -> ModelEntry:
        try:
            return await models.retrain()
        except (RetrainInProgressError, NoTrainingDataError) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return router
