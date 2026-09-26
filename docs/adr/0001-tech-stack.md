# Tech stack: Python/FastAPI backend, Next.js frontend, Postgres, one monorepo

We build PromoPilot as a single public monorepo (`backend/`, `frontend/`, `docs/`) with the stack fixed in SPEC.md §7.5, because judges must be able to clone and run everything with only Docker installed, and the ML/optimisation work (LightGBM, statsmodels, OR-Tools CP-SAT, LangGraph) is Python-native while the demo UI benefits from a typed React stack. Versions are pinned by lockfiles (`backend/uv.lock`, `frontend/pnpm-lock.yaml`); the versions below were the latest stable at setup (2026-09-25).

| Layer | Choice (version at E0) |
|---|---|
| Backend | Python 3.12, FastAPI 0.141, Pydantic 2.13, SQLAlchemy 2.1 async + asyncpg, structlog; managed by uv 0.12 |
| Agents / ML / optimisation | LangGraph, LightGBM, scikit-learn, statsmodels, OR-Tools CP-SAT: added and pinned in the epic that first needs them (E3–E8) |
| DB | PostgreSQL 16 (also the LangGraph checkpointer) |
| Frontend | Next.js 16 (App Router, standalone output), React 19, TypeScript strict, Tailwind 4, shadcn/ui, zod 4; pnpm 11, Node 24 |
| API contract | OpenAPI from FastAPI → `openapi-typescript` (`make api-types`); zod schemas `satisfies` the generated types so drift fails `tsc` |
| Testing | pytest, pytest-asyncio, hypothesis, testcontainers Postgres, coverage; Vitest + Testing Library; Playwright |
| Quality | ruff, mypy strict, ESLint + Prettier, pre-commit |
| Ops | Multi-stage Docker images, docker compose, GitHub Actions |

## Setup-time decisions (confirmed with the owner, not in SPEC.md)

- **`make dev` is hybrid**: Postgres runs in Docker; API (`uvicorn --reload`) and web (`next dev`) run natively for fast reload. The full containerised stack is `make up`; `make demo` (E11) stays Docker-only.
- **`/health` is a liveness endpoint**: always HTTP 200 while the process runs; `status` is `ok` or `degraded` with per-check detail (`database`, `model_registry`). `model_registry` reported `not_initialised` until E4; it is now `ok` or `missing` (ADR 0023).
- **The web app calls the API server-side** (Next.js server components using `API_URL`), so there is no CORS surface and the same code works inside compose (`http://api:8000`).
- **Makefile recipes are POSIX sh.** On Windows, run `make` from Git Bash; the Makefile refuses to run under cmd.exe/PowerShell.

## Spec-time decisions (E1, confirmed with the owner)

- **LLM providers**: OpenAI is the primary provider and Anthropic (`claude-sonnet-5`) the fallback, selected by `LLM_PROVIDER`; model IDs come from env (`OPENAI_MODEL`, `ANTHROPIC_MODEL`) so they can change without code changes. `replay` is used for CI and `make demo`.
- **Planning sessions run in the background**: `POST /api/sessions` returns the session id at once and `GET /api/sessions/{id}` reports its status, from the walking skeleton (E3) onwards, so the interrupts and SSE stream of E8 do not change the API's shape.
- **The browser reaches the API through Next.js route handlers**: client components call same-origin `/api/...` routes that forward to `API_URL` (including the SSE trace stream), so there is still no CORS surface and one public URL.
- **`make demo` trains models at first start**: the demo container generates data and trains the models (seeded, deterministic) into a Docker volume on first run, instead of committing model binaries; the whole first start should take about 5 minutes or less.
