# PromoPilot

Agentic retail promotion planner for the ET AI Hackathon (Problem 3, Retail: Autonomous Promotion Planner). A planning brief in plain English becomes a promotion plan that respects inventory, margin and budget constraints, with every number coming from deterministic tools and a human approving the result.

> **Status:** epic E3 (walking skeleton). `make data` generates the synthetic world. A brief typed on the home page becomes a naive plan on the session page (ADR 0020), and the Docker stack does this with no API key (ADR 0022). Real forecasting, optimisation and the full agent arrive in later epics; see [SPEC.md](SPEC.md) §15 for the delivery plan.

## Quickstart

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 24 with [pnpm](https://pnpm.io/) 11, GNU make. On Windows, run `make` from **Git Bash**.

```bash
git clone https://github.com/asalwania/promopilot.git
cd promopilot
make setup   # creates .env from .env.example, installs backend + frontend deps, git hooks
make dev     # Postgres in Docker; API on :8000 and web on :3000 with hot reload
```

Open http://localhost:3000. Type a brief and click **Plan it**. The app starts a planning session and opens `/sessions/<id>`. That page polls the session every second while it is `planning`. It then shows the planning request the agent read and the plan table, or the reason the session failed (ADR 0021). The home page also fetches `/api/health` from its own origin and shows the database status.

The browser never calls the API directly. Next.js route handlers forward every same-origin `/api/*` request to `API_URL` with the path, query, method, body and status unchanged, and stream the response (ADR 0001, ADR 0018). There is one public URL and no CORS.

| Setting | Default | Meaning |
|---|---|---|
| `API_URL` (`.env`) | `http://localhost:8000` | Where the Next.js server forwards `/api/*`. Docker Compose sets it to `http://api:8000` |

To run the full stack in containers with only Docker installed:

```bash
docker compose up -d --build --wait   # or: make up
docker compose exec api python -m promopilot.datagen --out /tmp/data --load   # the seed-42 world, about a minute
```

The Docker stack needs no API key. Compose runs the api with `LLM_PROVIDER=replay` and the cassettes baked into its image, whatever `.env` says (ADR 0022). CI runs exactly these steps, then Playwright types the brief from `backend/cassettes/briefs.json`, clicks **Plan it** and waits for the plan table.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install dependencies and pre-commit hooks |
| `make dev` | Postgres in Docker; API and web natively with hot reload |
| `make up` / `make down` | Full stack (postgres, api, web) in Docker |
| `make test` | Backend + frontend unit/API tests (no Docker, no LLM). Fails if line coverage of the core packages (datagen, models, optimizer, simulator, agents, economics, domain) is below 85% |
| `make test-integration` | Backend tests against a throwaway Postgres (testcontainers) |
| `make test-e2e` | Playwright against a running stack with data loaded: health, and brief to plan table |
| `make lint` / `make format` | ruff, ESLint, Prettier |
| `make typecheck` | mypy strict, tsc strict |
| `make api-types` | Export OpenAPI to `docs/openapi.json` and regenerate frontend types |
| `make data` | Generate the seeded synthetic dataset into `data/generated/` (Parquet) and its hidden ground truth into `data/ground_truth/`, then load the tables into Postgres (starts it if needed) |
| `make record-cassettes` | Re-record the LLM cassettes with a live OpenAI key (see [LLM providers](#llm-providers)) |
| `make train`, `make eval`, `make demo` | Arrive in epics E4, E9, E11 |

## Synthetic data

The organisers give no data, so `make data` generates a synthetic multi-region Indian retailer whose true demand parameters are known (SPEC §8, ADR 0003). Seed 42 and the defaults in [`backend/src/promopilot/datagen/config.yaml`](backend/src/promopilot/datagen/config.yaml) cover:
- 200 SKUs in 8 categories, and 4 regions × 5 stores with a segment mix per store.
- A festival calendar on real dates (week 0 = 2024-09-30), 104 weeks of per-segment sales and promotion history.
- Competitor prices, weekly inventory, 200,000 baskets, and a 52-week future horizon.

| Setting | Default | Meaning |
|---|---|---|
| `DATA_DIR` (`.env`) | `../data` | Output directory, relative to `backend/` |

For a different world, run `cd backend && uv run python -m promopilot.datagen --config my.yaml --seed 7 --out ../data --load`. The YAML only needs the keys it overrides. The same seed and config always give byte-identical files. Loading is idempotent: the first Alembic migration creates the tables, and every load replaces their rows in one transaction. The app reads them through `promopilot.data.RetailData`, whose time-dependent queries take an explicit as-of week and never return sales, promotions, baskets or competitor prices at or after it (ADR 0008). Only `promopilot.datagen` and `promopilot.evals` may read `data/ground_truth/`.

## LLM providers

Agents reach an LLM only through `promopilot.llm` (ADR 0001, ADR 0019). `LLM_PROVIDER` picks the provider:

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` (`.env`) | `replay` | `replay` answers from recorded cassettes and needs no key. `openai` calls OpenAI live |
| `LLM_CASSETTE_DIR` (`.env`) | `cassettes` | One JSON file per request hash, relative to `backend/` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` (`.env`) | empty | Needed only for `openai` and `make record-cassettes`. The model must accept `temperature=0`: use `gpt-4.1-mini` (the `gpt-5` reasoning models reject it). Keep the key in `.env`, never commit it |

In replay mode, a request with no recorded cassette fails with `CassetteMissError` naming its hash. This usually means a prompt or schema changed and the cassettes need re-recording. Cassettes store only the request content and the parsed response, never headers or keys. Tests use `FakeProvider` or `ReplayProvider` and never call a real LLM.

### Recording cassettes

The committed cassettes in `backend/cassettes/` answer every brief in `backend/cassettes/briefs.json` over the seed-42 world. A unit test checks this, so CI fails when they go stale. To re-record them after changing a prompt, a schema or the default world:

```bash
make data               # the world the cassettes are recorded against
make record-cassettes   # needs OPENAI_API_KEY and OPENAI_MODEL in .env; makes one live call per brief
make up                 # rebuild the api image with the new cassettes
```

`make record-cassettes` plans each brief through OpenAI and records every LLM request. It replaces the cassettes only if every brief reaches a plan. If one fails, it names the brief, exits non-zero and changes nothing. A full run removes stale cassettes, so commit the whole directory (ADR 0022).

## API

| Method | Path | Response |
|---|---|---|
| POST | `/api/sessions` | Start a planning session from `{"brief": "..."}` (1–2000 characters, not blank; otherwise `422`). Returns `202 {"session_id"}` at once; planning runs in the background |
| GET | `/api/sessions/{id}` | `{session_id, status, brief, planning_request, plan_revision, error}`; `404` if unknown. `status` is `planning`, then `awaiting_approval` with plan revision 1, or `failed` with an `error` saying why |
| GET | `/health`, `/api/health` | Always `200` while the process runs. `/health` is for the container healthcheck; the web app uses `/api/health` through its proxy. `{"status": "ok" \| "degraded", "version", "checks": {"database": "ok" \| "error", "model_registry": "not_initialised"}}` |

In E3 a planning session is a walking skeleton (ADR 0020). A minimal Context agent reads the brief into a planning request: scope, a promo window chosen from the weeks after the as-of week, and a marketing budget in rupees. If any of these is missing, the session fails and the error names it. A naive greedy planner then offers 20% off to All customers on in-scope SKUs, ranked by base margin, within the budget. It has no uplift model yet, so each line's expected incremental profit is minus its promo cost. E4–E8 replace it. The as-of week is the first week after the loaded sales history.

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
- [ADR 0015: Promo accounting details: charm prices, fixed cost in profit, money as float rupees](docs/adr/0015-promo-accounting-details.md)
- [ADR 0016: Synthetic world details: real calendar dates, overstock per SKU, hidden future competitor prices](docs/adr/0016-synthetic-world-details.md)
- [ADR 0017: The oracle totals a plan jointly, attributes effects one line at a time, and caps only promoted SKUs](docs/adr/0017-oracle-attribution-and-stock-cap.md)
- [ADR 0018: The web proxy forwards `/api/*` paths unchanged, and health is also served at `/api/health`](docs/adr/0018-same-origin-api-proxy-paths.md)
- [ADR 0019: The LLM layer is async, and cassettes are one JSON file per provider-independent request hash](docs/adr/0019-llm-layer-and-cassettes.md)
- [ADR 0020: Walking-skeleton sessions: rupee budgets, a week table for the LLM, a naive planner with no uplift](docs/adr/0020-walking-skeleton-session-decisions.md)
- [ADR 0021: The session page polls every second, stops on any settled status or failed read, and shows plan numbers in en-IN rupees](docs/adr/0021-session-page-polling-and-plan-display.md)
- [ADR 0022: The Docker stack always replays cassettes baked into the api image, and `make record-cassettes` replaces them all or none](docs/adr/0022-no-key-skeleton-and-cassette-recording.md)

The domain glossary is [CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE)
