"""The world an eval plans in and scores against (ADR 0056): one generated dataset, its ground
truth behind the oracle, and demand and relations models fitted on it as of each scenario's
week.

The eval builds its own world instead of reading Postgres and the model registry, so a scenario
can be planned at any as-of week without sales after it reaching the models (ADR 0008), and a
run needs neither `make data`, `make train` nor Docker. The same datagen config and seed give
the same world as `make data`.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from promopilot.data import InMemoryRetailData
from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate, load_config
from promopilot.evals.oracle import Oracle
from promopilot.models import demand, relations
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.models.relations import Relations
from promopilot.models.training import DEFAULT_SEED

FITTED_AT = datetime(1970, 1, 1, tzinfo=UTC)
"""An in-memory fit is never registered, so it records no training time: runs stay identical."""


@dataclass(frozen=True)
class FittedModels:
    """Demand, and relations fitted on it, as of one week."""

    demand: DemandModel
    relations: Relations


class _Fixed[T]:
    """A model source that always serves one fitted model (`LatestModel`'s `get`)."""

    def __init__(self, entry: RegisteredModel, model: T) -> None:
        self._loaded = (entry, model)

    async def get(self) -> tuple[RegisteredModel, T]:
        return self._loaded


@dataclass(frozen=True)
class ModelSources:
    demand: _Fixed[DemandModel]
    relations: _Fixed[Relations]


class EvalWorld:
    """A generated dataset with its ground truth, and the models fitted on it per as-of week,
    each fitted once with `fit_seed` and kept."""

    def __init__(
        self,
        dataset: GeneratedDataset,
        *,
        fit_seed: int = DEFAULT_SEED,
        fitted: dict[int, FittedModels] | None = None,
    ) -> None:
        self._dataset = dataset
        self._fit_seed = fit_seed
        self._fitted: dict[int, FittedModels] = dict(fitted or {})
        self.oracle = Oracle.from_dataset(dataset)

    @classmethod
    def generated(cls, seed: int, config: GeneratorConfig | None = None) -> "EvalWorld":
        """The world `make data` generates with this seed (and the default config)."""
        return cls(generate(config or load_config(), seed))

    @property
    def seed(self) -> int:
        return self._dataset.seed

    def data(self, as_of_week: int) -> InMemoryRetailData:
        """The data tables, read with the clock at `as_of_week`."""
        return InMemoryRetailData(self._dataset, as_of_week=as_of_week)

    async def models(self, as_of_week: int) -> ModelSources:
        """The models fitted on the history before `as_of_week`, fitting them the first time."""
        fitted = self._fitted.get(as_of_week)
        if fitted is None:
            fitted = await asyncio.to_thread(self._fit, as_of_week)
            self._fitted[as_of_week] = fitted
        return ModelSources(
            demand=_Fixed(self._entry(ModelKind.DEMAND, as_of_week), fitted.demand),
            relations=_Fixed(self._entry(ModelKind.RELATIONS, as_of_week), fitted.relations),
        )

    def _fit(self, as_of_week: int) -> FittedModels:
        dataset = self._dataset
        sales = dataset.sales_weekly.copy()
        sales["segment_units"] = sales["segment_units"].map(json.loads)
        # Each fit reads only the history before its as-of week (ADR 0008).
        history = DemandHistory(
            products=dataset.products,
            stores=dataset.stores,
            calendar=dataset.calendar,
            sales_weekly=sales,
            promotions_history=dataset.promotions_history,
            competitor_prices=dataset.competitor_prices,
        )
        model = demand.fit(history, as_of_week, self._fit_seed)
        found = relations.fit(history, dataset.baskets, model, as_of_week, self._fit_seed)
        return FittedModels(demand=model, relations=found)

    def _entry(self, kind: ModelKind, as_of_week: int) -> RegisteredModel:
        return RegisteredModel(
            model_id=uuid5(NAMESPACE_URL, f"promopilot:eval:{self.seed}:{kind.value}:{as_of_week}"),
            kind=kind,
            version=1,
            trained_at=FITTED_AT,
            as_of_week=as_of_week,
            metrics={},
            artifact_path="",
        )
