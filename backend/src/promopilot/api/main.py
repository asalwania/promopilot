"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI

from promopilot import __version__
from promopilot.api.schemas import HealthChecks, HealthResponse
from promopilot.config import Settings
from promopilot.data.database import PostgresDatabaseProbe


class DatabaseProbe(Protocol):
    async def is_healthy(self) -> bool: ...


def create_app(*, database_probe: DatabaseProbe) -> FastAPI:
    app = FastAPI(title="PromoPilot API", version=__version__)

    # `/health` serves the container healthcheck; `/api/health` is what the web proxy forwards.
    @app.get("/health")
    @app.get("/api/health")
    async def health() -> HealthResponse:
        try:
            database_ok = await database_probe.is_healthy()
        except Exception:
            database_ok = False
        return HealthResponse(
            status="ok" if database_ok else "degraded",
            version=__version__,
            checks=HealthChecks(
                database="ok" if database_ok else "error",
                model_registry="not_initialised",
            ),
        )

    return app


def build_app() -> FastAPI:
    """Production entry point: `uvicorn --factory promopilot.api.main:build_app`."""
    settings = Settings()
    probe = PostgresDatabaseProbe(settings.database_url)
    app = create_app(database_probe=probe)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await probe.dispose()

    app.router.lifespan_context = lifespan
    return app
