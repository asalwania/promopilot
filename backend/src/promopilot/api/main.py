"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot import __version__
from promopilot.agents import OptimisingPlanner
from promopilot.agents.tools import ToolRegistry
from promopilot.agents.tools.estimate_demand import estimate_demand_tool
from promopilot.agents.tools.generate_candidates import generate_candidates_tool
from promopilot.agents.tools.get_competitor_gaps import get_competitor_gaps_tool
from promopilot.agents.tools.get_relations import get_relations_tool
from promopilot.agents.tools.holidays import get_holidays_tool
from promopilot.agents.tools.inventory_status import get_inventory_status_tool
from promopilot.agents.tools.run_optimizer import run_optimizer_tool
from promopilot.agents.tools.scope_data import get_scope_data_tool
from promopilot.api.catalog import CatalogService, catalog_router
from promopilot.api.competitors import CompetitorService, competitors_router
from promopilot.api.models import ModelService, models_router
from promopilot.api.relations import RelationsService, relations_router
from promopilot.api.schemas import HealthChecks, HealthResponse
from promopilot.api.sessions import SessionService, sessions_router
from promopilot.config import Settings
from promopilot.data import RetailData, SessionStore, migrate
from promopilot.data.database import PostgresDatabaseProbe
from promopilot.domain import CompanyPolicy
from promopilot.llm import build_provider
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from promopilot.models.relations import Relations
from promopilot.models.serving import LiveRelations
from promopilot.optimizer import CandidateStore, SolverSettings

log = structlog.get_logger(__name__)


class DatabaseProbe(Protocol):
    async def is_healthy(self) -> bool: ...


class ModelStatus(Protocol):
    async def is_loaded(self) -> bool: ...


def create_app(
    *,
    database_probe: DatabaseProbe,
    model_status: ModelStatus,
    sessions: SessionService,
    models: ModelService | None = None,
    competitors: CompetitorService | None = None,
    relations: RelationsService | None = None,
    catalog: CatalogService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await sessions.recover_interrupted()
        except Exception:
            # Liveness first (ADR 0001): /health reports the database as it recovers.
            log.exception("sessions.recover_failed")
        # Load the latest model now; if there is none, /health keeps retrying (ADR 0023).
        await model_status.is_loaded()
        yield
        await sessions.close()

    app = FastAPI(title="PromoPilot API", version=__version__, lifespan=lifespan)
    app.include_router(sessions_router(sessions))
    if models is not None:
        app.include_router(models_router(models))
    if competitors is not None:
        app.include_router(competitors_router(competitors))
    if relations is not None:
        app.include_router(relations_router(relations))
    if catalog is not None:
        app.include_router(catalog_router(catalog))

    # `/health` serves the container healthcheck; `/api/health` is what the web proxy forwards.
    @app.get("/health")
    @app.get("/api/health")
    async def health() -> HealthResponse:
        try:
            database_ok = await database_probe.is_healthy()
        except Exception:
            database_ok = False
        try:
            model_loaded = await model_status.is_loaded()
        except Exception:
            model_loaded = False
        return HealthResponse(
            status="ok" if database_ok and model_loaded else "degraded",
            version=__version__,
            checks=HealthChecks(
                database="ok" if database_ok else "error",
                model_registry="ok" if model_loaded else "missing",
            ),
        )

    return app


def build_app() -> FastAPI:
    """Production entry point: `uvicorn --factory promopilot.api.main:build_app`."""
    settings = Settings()
    probe = PostgresDatabaseProbe(settings.database_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    registry = ModelRegistry(engine, settings.model_dir)
    demand_model = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    # Relations are served only on the demand model they were fitted on (ADR 0033).
    relations_model = LiveRelations(
        LatestModel(registry, ModelKind.RELATIONS, Relations), demand_model
    )
    data = RetailData(engine)
    models = ModelService(
        registry=registry, data=data, live=demand_model, live_relations=relations_model
    )
    policy = CompanyPolicy()
    solver_settings = SolverSettings(
        time_limit_seconds=settings.optimizer_time_limit_seconds,
        workers=settings.optimizer_workers,
    )
    # Sessions plan with the latest demand model and the live relations model (ADR 0038).
    sessions = SessionService(
        store=SessionStore(engine),
        data=data,
        llm=build_provider(settings),
        planner=OptimisingPlanner(
            demand_model,
            relations_model,
            data,
            policy=policy,
            settings=solver_settings,
            seed=settings.optimizer_seed,
        ),
    )
    app = create_app(
        database_probe=probe,
        model_status=demand_model,
        sessions=sessions,
        models=models,
        competitors=CompetitorService(data, policy=policy),
        relations=RelationsService(relations_model, data),
        catalog=CatalogService(data, policy=policy),
    )
    # The agents' tools (ADR 0025): the model is resolved per call, so a retrain is picked up,
    # and so is the as-of week, so newly loaded data moves the data tools' clock (ADR 0032).
    # Generated promo options wait here for the optimiser (ADR 0035, ADR 0036).
    app.state.candidates = CandidateStore()
    app.state.tools = ToolRegistry(
        [
            estimate_demand_tool(demand_model, policy=policy),
            get_scope_data_tool(data),
            get_inventory_status_tool(data, data.default_as_of_week, policy=policy),
            get_holidays_tool(data, data.default_as_of_week),
            get_competitor_gaps_tool(data, data.default_as_of_week, policy=policy),
            get_relations_tool(relations_model, data),
            generate_candidates_tool(
                demand_model,
                relations_model,
                data,
                data.default_as_of_week,
                policy=policy,
                store=app.state.candidates,
            ),
            run_optimizer_tool(
                app.state.candidates,
                policy=policy,
                settings=solver_settings,
                seed=settings.optimizer_seed,
            ),
        ]
    )
    serve = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            await migrate(engine)
        except Exception:
            log.exception("database.migrate_failed")
        try:
            async with serve(application):
                yield
        finally:
            await engine.dispose()
            await probe.dispose()

    app.router.lifespan_context = lifespan
    return app
