"""Train the demand model, then the relations model, and register both (`make train`; SF-02)."""

import asyncio
from dataclasses import dataclass

from promopilot.data import RetailData
from promopilot.models import demand, relations
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, ModelRegistry, RegisteredModel
from promopilot.models.relations import Relations

DEFAULT_SEED = 42
"""The seed `make train` and `POST /api/models/retrain` fit with (ADR 0026)."""


@dataclass(frozen=True)
class TrainedModels:
    demand: RegisteredModel
    demand_model: DemandModel
    relations: RegisteredModel
    relations_model: Relations


async def train_models(
    data: RetailData, registry: ModelRegistry, *, as_of_week: int, seed: int
) -> TrainedModels:
    """Fit demand, then relations on it, on the history before `as_of_week`.

    Both are registered only once both fits succeed; the relations entry records the demand
    version it was fitted on (ADR 0029).
    """
    history = DemandHistory(
        products=await data.products(),
        stores=await data.stores(),
        calendar=await data.calendar(),
        sales_weekly=await data.sales_history(as_of_week),
        promotions_history=await data.promotions_history(as_of_week),
        competitor_prices=await data.competitor_prices(as_of_week),
    )
    baskets = await data.baskets(as_of_week)
    # Fitting is CPU-bound: keep the event loop free for the API (retrain, #29).
    demand_model = await asyncio.to_thread(demand.fit, history, as_of_week, seed)
    relations_model = await asyncio.to_thread(
        relations.fit, history, baskets, demand_model, as_of_week, seed
    )
    demand_entry = await registry.register(
        ModelKind.DEMAND, demand_model, as_of_week=as_of_week, metrics=demand_model.metrics
    )
    relations_entry = await registry.register(
        ModelKind.RELATIONS,
        relations_model,
        as_of_week=as_of_week,
        metrics={**relations_model.metrics, "demand_version": float(demand_entry.version)},
    )
    return TrainedModels(
        demand=demand_entry,
        demand_model=demand_model,
        relations=relations_entry,
        relations_model=relations_model,
    )
