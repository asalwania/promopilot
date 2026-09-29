# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.12-slim AS runtime
# LightGBM needs the OpenMP runtime.
RUN apt-get update     && apt-get install -y --no-install-recommends libgomp1     && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app
WORKDIR /app
# The model-artifacts volume mounts here; it copies this owner on first use.
RUN mkdir models && chown app:app models
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Recorded LLM responses: the image plans briefs with LLM_PROVIDER=replay and no key (ADR 0019).
COPY --chown=app:app cassettes ./cassettes
# The recorded full eval run that GET /api/evals/latest serves in Docker (ADR 0073).
COPY --chown=app:app evals/published ./evals/published
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "--factory", "promopilot.api.main:build_app", "--host", "0.0.0.0", "--port", "8000"]
