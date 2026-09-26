# PromoPilot

Agentic retail promotion planner for the ET AI Hackathon (Problem 3, Retail: Autonomous Promotion Planner). A planning brief in plain English becomes a promotion plan that respects inventory, margin and budget constraints, with every number coming from deterministic tools and a human approving the result.

> **Status:** epic E0 (bootstrap). The API serves `/health` and the web app shows it. Planning features arrive in later epics; see [SPEC.md](SPEC.md) §15 for the delivery plan.

## Quickstart

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 24 with [pnpm](https://pnpm.io/) 11, GNU make. On Windows, run `make` from **Git Bash**.

```bash
git clone https://github.com/asalwania/promopilot.git
cd promopilot
make setup   # creates .env from .env.example, installs backend + frontend deps, git hooks
make dev     # Postgres in Docker; API on :8000 and web on :3000 with hot reload
```

Open http://localhost:3000. The home page calls the API's `/health` and shows the database status.

To run the full stack in containers with only Docker installed:

```bash
docker compose up -d --build --wait   # or: make up
```

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install dependencies and pre-commit hooks |
| `make dev` | Postgres in Docker; API and web natively with hot reload |
| `make up` / `make down` | Full stack (postgres, api, web) in Docker |
| `make test` | Backend + frontend unit/API tests (no Docker, no LLM) |
| `make test-integration` | Backend tests against a throwaway Postgres (testcontainers) |
| `make test-e2e` | Playwright against a running stack |
| `make lint` / `make format` | ruff, ESLint, Prettier |
| `make typecheck` | mypy strict, tsc strict |
| `make api-types` | Export OpenAPI to `docs/openapi.json` and regenerate frontend types |
| `make data`, `make train`, `make eval`, `make demo` | Arrive in epics E2, E4, E9, E11 |

## API

| Method | Path | Response |
|---|---|---|
| GET | `/health` | Always `200` while the process runs. `{"status": "ok" \| "degraded", "version", "checks": {"database": "ok" \| "error", "model_registry": "not_initialised"}}` |

Interactive docs are at http://localhost:8000/docs. The machine-readable contract is [docs/openapi.json](docs/openapi.json).

## Repository layout

```
backend/    FastAPI app (src/promopilot), tests, uv project
frontend/   Next.js App Router app, Vitest unit tests, Playwright e2e
docs/adr/   Architecture decision records
docs/agents/ Agent workflow config (issue tracker, triage labels, domain docs)
```

## Architecture decisions

- [ADR 0001: Tech stack](docs/adr/0001-tech-stack.md)
- [ADR 0002: Agents decide, tools compute, humans approve](docs/adr/0002-agents-decide-tools-compute.md)
- [ADR 0003: Synthetic data with hidden ground truth](docs/adr/0003-synthetic-data-with-hidden-ground-truth.md)
- [ADR 0004: Region-level plan lines with pooled regional stock](docs/adr/0004-region-level-plan-lines-with-pooled-stock.md)
- [ADR 0005: One profit objective, with explicit promo economics](docs/adr/0005-single-profit-objective-and-promo-economics.md)
- [ADR 0006: Segment-exclusive offers, plus an "All customers" open promotion](docs/adr/0006-segment-exclusive-offers.md)
- [ADR 0007: Company policy is tighten-only; plan-level minimum margin](docs/adr/0007-company-policy-is-tighten-only.md)
- [ADR 0008: Planning happens at a configurable as-of week](docs/adr/0008-as-of-week-clock.md)
- [ADR 0009: Shared domain value types live in `promopilot.domain`](docs/adr/0009-shared-domain-value-types.md)
- [ADR 0010: Test data is generated on the fly; tests may compare against its ground truth](docs/adr/0010-test-data-from-datagen-with-ground-truth.md)
- [ADR 0011: Promo economics are shared definitions; the oracle scores expected outcomes, capped at stock](docs/adr/0011-shared-promo-economics-and-oracle-scoring.md)
- [ADR 0012: Constraint satisfaction is checked on plan-time values; the oracle breach rate is reported](docs/adr/0012-constraint-satisfaction-on-plan-time-values.md)
- [ADR 0013: Substitute detection uses FDR control plus an effect-size threshold](docs/adr/0013-substitute-detection-with-fdr-and-effect-size.md)
- [ADR 0014: Clearance targets apply only to brief-named SKUs; a BUNDLE partner is locked](docs/adr/0014-clearance-targets-and-bundle-partners.md)

The domain glossary is [CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE)
