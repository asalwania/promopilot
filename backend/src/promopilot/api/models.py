"""The model registry over HTTP: list the versions, retrain the demand model (SF-02, ADR 0026).

`POST /api/models/retrain` holds the request open while the model fits in a worker thread,
so the API keeps serving, and answers with the new version once it is registered and live.
"""

import asyncio

from fastapi import APIRouter, HTTPException, status

from promopilot.api.schemas import ModelEntry, ModelList
from promopilot.data import RetailData
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelRegistry
from promopilot.models.training import DEFAULT_SEED, train_demand_model


class RetrainInProgressError(Exception):
    """A retrain is already running in this API process."""


class NoTrainingDataError(Exception):
    """No sales history is loaded to train on."""


class ModelService:
    """The registered demand models and the one live in this API process."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        data: RetailData,
        live: LatestModel[DemandModel],
        seed: int = DEFAULT_SEED,
    ) -> None:
        self._registry = registry
        self._data = data
        self._live = live
        self._seed = seed
        self._retraining = asyncio.Lock()

    async def list(self) -> ModelList:
        loaded = await self._live.get()
        live_id = None if loaded is None else loaded[0].model_id
        return ModelList(
            models=[
                ModelEntry.of(entry, live=entry.model_id == live_id)
                for entry in await self._registry.list()
            ]
        )

    async def retrain(self) -> ModelEntry:
        """Fit on the default as-of week with the default seed, register, and go live."""
        # No await between the check and the acquire, so two requests cannot both pass.
        if self._retraining.locked():
            raise RetrainInProgressError("a retrain is already running; try again when it finishes")
        async with self._retraining:
            try:
                as_of_week = await self._data.default_as_of_week()
            except LookupError as error:
                raise NoTrainingDataError(str(error)) from error
            entry, model = await train_demand_model(
                self._data, self._registry, as_of_week=as_of_week, seed=self._seed
            )
            self._live.set((entry, model))
        return ModelEntry.of(entry, live=True)


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
