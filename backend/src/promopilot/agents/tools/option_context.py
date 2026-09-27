"""The option context a planning request is generated in, for the tools that generate promo
options (`generate_candidates`, `compare_mechanisms`).

The request must be for the tool's bound as-of week (ADR 0032). The latest demand model and
the live relations model are resolved on every call (ADR 0025, ADR 0033), and stock is
pooled from the as-of week's inventory (ADR 0004).
"""

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.catalogue_filter import in_scope
from promopilot.agents.tools.estimate_demand import DemandModelSource, ModelVersion
from promopilot.agents.tools.get_relations import RelationsSource
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.agents.tools.registry import ToolCallError
from promopilot.domain import CompanyPolicy, PlanningRequest
from promopilot.models.registry import RegisteredModel
from promopilot.optimizer import OptionContext


class OptionDataSource(Protocol):
    """The reads option generation makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...


@dataclass(frozen=True)
class LoadedOptionContext:
    context: OptionContext
    as_of_week: int
    demand_model: ModelVersion
    relations_model: ModelVersion


async def load_option_context(
    request: PlanningRequest,
    demand_models: DemandModelSource,
    relations_models: RelationsSource,
    data: OptionDataSource,
    as_of_week: AsOfWeekSource,
    policy: CompanyPolicy,
) -> LoadedOptionContext:
    """Raises `ToolCallError`: `invalid_input` for another as-of week or a scope the data
    lacks, `model_unavailable` with no model, `data_unavailable` with no inventory."""
    week = await current_as_of_week(as_of_week)
    if request.as_of_week != week:
        raise ToolCallError(
            "invalid_input",
            f"the planning request is for as-of week {request.as_of_week}, "
            f"but planning is at as-of week {week}",
        )
    demand = await demand_models.get()
    relations = await relations_models.get()
    if demand is None or relations is None:
        raise ToolCallError(
            "model_unavailable", "no demand model, or no relations model fitted on it, yet"
        )
    stores = await data.stores()
    products = await data.products()
    in_scope(
        products,
        sorted(stores["region"].unique()),
        regions=request.scope.regions,
        categories=request.scope.categories,
        sku_ids=request.scope.sku_ids or None,
    )
    try:
        snapshot = await data.inventory(week)
    except LookupError as error:
        raise ToolCallError("data_unavailable", str(error)) from error
    return LoadedOptionContext(
        context=OptionContext(
            demand_model=demand[1],
            relations=relations[1],
            products=products,
            stock=pooled_stock(snapshot, stores, policy),
            policy=policy,
        ),
        as_of_week=week,
        demand_model=_version(demand[0]),
        relations_model=_version(relations[0]),
    )


def _version(entry: RegisteredModel) -> ModelVersion:
    return ModelVersion(model_id=entry.model_id, version=entry.version, as_of_week=entry.as_of_week)
