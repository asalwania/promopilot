"""Print the OpenAPI document (the frontend contract): `python -m promopilot.api.openapi`."""

import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.agents import OptimisingPlanner
from promopilot.api.catalog import CatalogService
from promopilot.api.competitors import CompetitorService
from promopilot.api.main import create_app
from promopilot.api.models import ModelService
from promopilot.api.relations import RelationsService
from promopilot.api.sessions import SessionService
from promopilot.data import RetailData, SessionStore
from promopilot.domain import CompanyPolicy
from promopilot.llm import FakeProvider
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from promopilot.models.relations import Relations
from promopilot.models.serving import LiveRelations
from promopilot.optimizer import SolverSettings
from promopilot.simulator import DEFAULT_RUNS, SimulationSettings


class _UnusedProbe:
    async def is_healthy(self) -> bool:
        return False

    async def is_loaded(self) -> bool:
        return False


def main() -> None:
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")  # never connects
    registry = ModelRegistry(engine, Path("unused"))
    demand = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    relations = LiveRelations(LatestModel(registry, ModelKind.RELATIONS, Relations), demand)
    sessions = SessionService(
        store=SessionStore(engine),
        data=RetailData(engine),
        llm=FakeProvider([]),
        planner=OptimisingPlanner(
            demand,
            relations,
            RetailData(engine),
            policy=CompanyPolicy(),
            settings=SolverSettings(),
            seed=0,
            simulation=SimulationSettings(n_runs=DEFAULT_RUNS, seed=0),
        ),
    )
    models = ModelService(
        registry=registry, data=RetailData(engine), live=demand, live_relations=relations
    )
    probe = _UnusedProbe()
    app = create_app(
        database_probe=probe,
        model_status=probe,
        sessions=sessions,
        models=models,
        competitors=CompetitorService(RetailData(engine), policy=CompanyPolicy()),
        relations=RelationsService(relations, RetailData(engine)),
        catalog=CatalogService(RetailData(engine), policy=CompanyPolicy()),
    )
    document = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    # Write bytes so Windows doesn't emit CRLF; CI diffs this file on Linux.
    sys.stdout.buffer.write(document.encode())


if __name__ == "__main__":
    main()
