"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot import __version__
from promopilot.agents.tools import ToolRegistry
from promopilot.agents.tools.estimate_demand import estimate_demand_tool
from promopilot.api.models import ModelService, models_router
from promopilot.api.schemas import HealthChecks, HealthResponse
from promopilot.api.sessions import SessionService, sessions_router
from promopilot.config import Settings
from promopilot.data import RetailData, SessionStore, migrate
from promopilot.data.database import PostgresDatabaseProbe
from promopilot.domain import CompanyPolicy
from promopilot.llm import build_provider
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry

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
    sessions = SessionService(
        store=SessionStore(engine), data=RetailData(engine), llm=build_provider(settings)
    )
    registry = ModelRegistry(engine, settings.model_dir)
    demand_model = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    models = ModelService(registry=registry, data=RetailData(engine), live=demand_model)
    app = create_app(
        database_probe=probe, model_status=demand_model, sessions=sessions, models=models
    )
    # The agents' tools (ADR 0025): the model is resolved per call, so a retrain is picked up.
    app.state.tools = ToolRegistry([estimate_demand_tool(demand_model, policy=CompanyPolicy())])
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
