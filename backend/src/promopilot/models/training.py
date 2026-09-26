"""Train the demand model on the loaded data and register it (`make train`; SF-02)."""

import asyncio

from promopilot.data import RetailData
from promopilot.models import demand
from promopilot.models.demand import DemandHistory
from promopilot.models.registry import ModelKind, ModelRegistry, RegisteredModel


async def train_demand_model(
    data: RetailData, registry: ModelRegistry, *, as_of_week: int, seed: int
) -> RegisteredModel:
    history = DemandHistory(
        products=await data.products(),
        stores=await data.stores(),
        calendar=await data.calendar(),
        sales_weekly=await data.sales_history(as_of_week),
        promotions_history=await data.promotions_history(as_of_week),
        competitor_prices=await data.competitor_prices(as_of_week),
    )
    # Fitting is CPU-bound: keep the event loop free for the API (retrain, #29).
    model = await asyncio.to_thread(demand.fit, history, as_of_week, seed)
    return await registry.register(
        ModelKind.DEMAND, model, as_of_week=as_of_week, metrics=model.metrics
    )
