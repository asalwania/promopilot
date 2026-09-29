"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot import __version__
from promopilot.agents import GraphTools, LLMPricing, PostgresCheckpoints
from promopilot.api.catalog import CatalogService, catalog_router
from promopilot.api.competitors import CompetitorService, competitors_router
from promopilot.api.demo import DemoRecordings
from promopilot.api.errors import DEFAULT_MAX_REQUEST_BODY_BYTES, install_error_handling
from promopilot.api.evals import EvalReportService, evals_router
from promopilot.api.models import ModelService, models_router
from promopilot.api.planning import build_planning
from promopilot.api.plans import PlanService, plans_router
from promopilot.api.rate_limit import RateLimiter
from promopilot.api.relations import RelationsService, relations_router
from promopilot.api.schemas import HealthChecks, HealthResponse, LLMStatus
from promopilot.api.sessions import SessionService, sessions_router
from promopilot.config import Settings
from promopilot.data import SessionStore, TraceStore, migrate
from promopilot.data.database import PostgresDatabaseProbe
from promopilot.llm import build_provider
from promopilot.logs import configure_logging

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
    plans: PlanService | None = None,
    evals: EvalReportService | None = None,
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
    llm: LLMStatus | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    llm_status = llm or LLMStatus(mode="replay", provider="replay", model=None)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            # The agent graph's checkpoints (ADR 0046); without them sessions answer 503.
            await sessions.open()
        except Exception:
            log.exception("sessions.checkpoints_unavailable")
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
    # One error schema for every error, and a request id on every response (ADR 0071).
    install_error_handling(app, max_request_body_bytes=max_request_body_bytes)
    # Per-client limits on starting and advancing planning, when set (ADR 0079).
    app.include_router(sessions_router(sessions, rate_limiter))
    if models is not None:
        app.include_router(models_router(models))
    if competitors is not None:
        app.include_router(competitors_router(competitors))
    if relations is not None:
        app.include_router(relations_router(relations))
    if catalog is not None:
        app.include_router(catalog_router(catalog))
    if plans is not None:
        app.include_router(plans_router(plans, rate_limiter))
    if evals is not None:
        app.include_router(evals_router(evals))

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
            # Replay or live, so the UI can say it is the no-key demo (ADR 0073).
            llm=llm_status,
        )

    return app


def build_app() -> FastAPI:
    """Production entry point: `uvicorn --factory promopilot.api.main:build_app`."""
    settings = Settings()
    # JSON lines that name the session they came from (ADR 0047).
    configure_logging(settings.log_format)
    probe = PostgresDatabaseProbe(settings.database_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    planning = build_planning(settings, engine)
    data, policy = planning.data, planning.policy
    models = ModelService(
        registry=planning.registry,
        data=data,
        live=planning.demand_model,
        live_relations=planning.relations_model,
    )
    store = SessionStore(engine)
    trace = TraceStore(engine)
    # Sessions run the agent graph, checkpointed in the app database (ADR 0046). Its planner
    # agent plans through the tool registry and falls back to the default sequence, which
    # plans with the latest demand model and the live relations model (ADR 0038, ADR 0049).
    # The Critic reviews each plan's risks with the configured thresholds and sends its
    # findings back to the planner agent at most 3 times (ADR 0051). A stored plan revision is
    # re-simulated with the same settings (ADR 0043).
    sessions = SessionService(
        store=store,
        tools=GraphTools(
            brief_data=data,
            planner=planning.planner,
            sessions=store,
            policy=policy,
            agent=planning.agent,
            # Every step is a trace event, and every LLM call is costed (ADR 0047).
            trace=trace,
            pricing=LLMPricing(prices=settings.llm_prices, usd_inr_rate=settings.usd_inr_rate),
            risk_thresholds=planning.risk_thresholds,
        ),
        llm=build_provider(settings),
        checkpoints=PostgresCheckpoints(settings.database_url),
        trace=trace,
        trace_poll_interval_s=settings.trace_poll_interval_s,
        # A background run that has not paused by then fails the session (ADR 0071).
        session_timeout_s=settings.session_timeout_seconds,
        # With no key, each session says whether it replays the demo recordings (ADR 0073).
        recordings=(
            DemoRecordings.read(settings.llm_cassette_dir)
            if settings.llm_provider == "replay"
            else None
        ),
    )
    app = create_app(
        database_probe=probe,
        model_status=planning.demand_model,
        sessions=sessions,
        max_request_body_bytes=settings.max_request_body_bytes,
        llm=LLMStatus.of(settings),
        rate_limiter=RateLimiter.from_settings(settings),
        models=models,
        competitors=CompetitorService(data, policy=policy),
        relations=RelationsService(planning.relations_model, data),
        catalog=CatalogService(data, policy=policy),
        plans=PlanService(
            revisions=store,
            demand_models=planning.demand_model,
            data=data,
            policy=policy,
            defaults=planning.simulation,
            timeout_s=settings.tool_timeout_seconds,
        ),
        # The latest `make eval` report, for the /evals dashboard (ADR 0069).
        evals=EvalReportService(settings.eval_report_dir),
    )
    # The agents' tools (ADR 0025), shared with the planner agent; no endpoint exposes them.
    app.state.candidates = planning.candidates
    app.state.tools = planning.tools
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
