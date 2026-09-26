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

The **Models** link in the header opens `/models`. It lists every registered model version, one table per kind, with its training time, as-of week and metrics, and marks the live one. **Retrain** calls `POST /api/models/retrain` and shows the elapsed time until the new version is live, then reloads the list; a failure shows the API's reason (ADR 0030).

The browser never calls the API directly. Next.js route handlers forward every same-origin `/api/*` request to `API_URL` with the path, query, method, body and status unchanged, and stream the response (ADR 0001, ADR 0018). There is one public URL and no CORS.

| Setting | Default | Meaning |
|---|---|---|
| `API_URL` (`.env`) | `http://localhost:8000` | Where the Next.js server forwards `/api/*`. Docker Compose sets it to `http://api:8000` |

To run the full stack in containers with only Docker installed:

```bash
docker compose up -d --build --wait   # or: make up
docker compose exec api python -m promopilot.datagen --out /tmp/data --load   # the seed-42 world, about a minute and a half
docker compose exec api python -m promopilot.models   # train and register the demand and relations models, about two minutes
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
| `make train` | Fit the demand model, then the relations model, on the loaded data (`make data` first) and register both (see [Demand model](#demand-model) and [Relations](#relations)) |
| `make eval`, `make demo` | Arrive in epics E9, E11 |

## Synthetic data

The organisers give no data, so `make data` generates a synthetic multi-region Indian retailer whose true demand parameters are known (SPEC §8, ADR 0003). Seed 42 and the defaults in [`backend/src/promopilot/datagen/config.yaml`](backend/src/promopilot/datagen/config.yaml) cover:
- 200 SKUs in 8 categories, and 4 regions × 5 stores with a segment mix per store.
- A festival calendar on real dates (week 0 = 2024-09-30), 104 weeks of per-segment sales and promotion history.
- Competitor prices, weekly inventory, 200,000 baskets, and a 52-week future horizon.

| Setting | Default | Meaning |
|---|---|---|
| `DATA_DIR` (`.env`) | `../data` | Output directory, relative to `backend/` |

For a different world, run `cd backend && uv run python -m promopilot.datagen --config my.yaml --seed 7 --out ../data --load`. The YAML only needs the keys it overrides. The same seed and config always give byte-identical files. Loading is idempotent: the first Alembic migration creates the tables, and every load replaces their rows in one transaction. The app reads them through `promopilot.data.RetailData`, whose time-dependent queries take an explicit as-of week and never return sales, promotions, baskets or competitor prices at or after it (ADR 0008). Only `promopilot.datagen` and `promopilot.evals` may read `data/ground_truth/`.

## Demand model

`make train` fits the baseline demand forecast on the data in Postgres (SPEC §9.1, ADR 0023). By default it uses the as-of week after the history (`--as-of-week` and `--seed`, default 42, override this) and registers a new version. The baseline is LightGBM. It forecasts no-promotion units per store × SKU × segment × week and learns only from weeks free of promotions and their 4-week pull-forward dip. It never sees history at or after the as-of week (ADR 0008). Before the final fit, it is validated on the last 12 weeks: the registry records holdout WAPE at the model grain (`baseline_wape`) and summed to store × SKU and region × SKU. On the seed-42 world these are 0.44, 0.25 and 0.14.

The promo response is fitted on the same history (ADR 0024). A Poisson GLM per SKU estimates:
- own-price elasticity per segment;
- competitor sensitivity, which controls for the competitor price index so the true elasticity is recovered (ADR 0016);
- mechanism effects;
- pull-forward.

Empirical Bayes shrinks each estimate toward its subcategory. `DemandModel.predict(options, context)` takes a batch of plan lines. It returns each one's mean and std of units, its uplift net of pull-forward, and its revenue, gross profit, margin and promo cost. `coefficients()` lists the fitted terms with their standard errors. The registry also records `response_skus_fitted` and `elasticity_median_std_error`. On the seed-42 world the median error of the recovered elasticities is 7.6%. Training takes 40 to 90 seconds.

| Setting | Default | Meaning |
|---|---|---|
| `MODEL_DIR` (`.env`) | `../models` | Model artifacts, relative to `backend/` (gitignored). Registry rows in Postgres hold paths relative to it. Docker Compose uses the `model-artifacts` volume at `/app/models` |

The API loads the latest demand model at startup and reports it in `/health`. `POST /api/models/retrain` retrains and swaps in the new version without a restart (see [API](#api)). For the Docker stack, train inside the api container (see the quick start) so the artifact lands on its volume.

Agents reach the model only through the tool registry (`promopilot.agents.tools`, ADR 0025). Each tool has a name, a JSON-schema input and output, and an async handler over injected dependencies. `registry.specs()` lists the tools with their schemas. `await registry.call(name, arguments)` returns `ToolOk` or a typed `ToolError` (`unknown_tool`, `invalid_input`, `model_unavailable` or `data_unavailable`) and never raises for a bad call. The first tool is `estimate_demand`. It takes 1 to 200 plan lines and optional competitor price overrides. For each line it returns `predict`'s numbers, unrounded, plus a per-segment table and the id and version of the model that produced them. The API builds the registry at startup (`app.state.tools`) and resolves the latest model on every call, so a newly registered model is used without a restart.

Three data tools show the planner the world as of a week (ADR 0032). `get_scope_data` lists regions with their stores, and the category → subcategory → SKU hierarchy with prices and KVI flags. `get_inventory_status` pools each SKU's stock per region from the snapshot before the as-of week: available stock (on hand minus safety stock), days of cover (Σ on hand ÷ Σ store daily demand) and an overstock flag (cover above the company-policy threshold). `get_holidays` lists national and regional holidays with their intensity per region and week, for a window after the as-of week. The tools never take the as-of week from the LLM: it is bound when they are built, and the API resolves the loaded data's default as-of week on every call.

`get_competitor_gaps` compares the competitor's latest price before the as-of week with our base price, per SKU × region (ADR 0031). It returns the competitor price index (CPI = competitor price ÷ base price), the gap (1 − CPI, positive when the competitor is cheaper), the competitor's promo flag and price week, and an **undercut** flag. A KVI is undercut when its CPI is below 1 minus the company-policy threshold (5% by default, ADR 0007). The tool filters by regions, categories, SKU ids and KVIs only. Like the data tools, it takes its as-of week from a bound source, never from the LLM (ADR 0032). `CompetitorGaps.within_kvi_tolerance(line)` is the optimiser's one-sided KVI price check: a promoted KVI's effective price must not exceed the competitor price by more than the tolerance (2% by default); pricing below the competitor always passes.

`promopilot.agents.resolution.BriefResolver` maps a brief's phrases to catalogue entities with no LLM: "Snacks and Beverages" to categories, "North and West" to regions, "400g namkeen packs" to exactly the Namkeen 400g SKUs, and "Diwali" to the weeks the calendar labels Diwali after the as-of week. Each candidate has a match score from 0 to 1 (1.0 only for an exact match). A resolution is ambiguous when its best score is below 0.7 or a runner-up is within 0.1 of it, so the Context agent can ask instead of guess.

## Relations

`make train` and retrain fit the relations model after the demand model, on the same history, and register it as its own kind (SPEC §9.2, ADR 0029). `promopilot.models.relations.fit(history, baskets, demand_model, as_of_week, seed)` returns `substitutes(sku)`, `complements(sku)` with lift and support, and `cross_effect(i, j)` with a standard error.

- **Substitutes**: for each within-subcategory pair, one pooled Poisson GLM on top of the demand model's fit estimates a symmetric cross-price effect θ. A pair is kept if its Benjamini–Hochberg q across all tested pairs is below 0.05 and θ ≥ 0.1 (ADR 0013).
- **Complements**: basket lift above 1.5, where at least 0.1% of baskets hold both SKUs. Where θ is estimable, the pair must also have θ < 0 with q < 0.05.

The thresholds live in `RelationsConfig`. The registry records them with the counts and the demand version used. On the seed-42 world, substitute precision/recall is 0.89/1.00 and complement precision/recall is 1.00/1.00.

The API serves the latest relations model only while it was fitted on the live demand model; otherwise `get_relations` answers `model_unavailable` and `GET /api/relations/{sku_id}` answers `503` (ADR 0033). The `get_relations` tool takes 1 to 50 SKU ids and returns each one's substitutes and complements with the model's id and version.

**Cannibalisation and halo** (ADR 0033). `line_effects(lines, relations, demand_model, products)` returns one row per plan line and each SKU it moves in its region, in scope or not (ADR 0005). Each row has the SKU's baseline units, the change in units and in percent, the change in profit at its base margin, and that change as cannibalised or halo profit. A detected relation moves units by baseline × (exp(Σ θ·log(p_eff/base)) − 1) over the promo weeks and targeted segments. `pairwise_cannibalisation(line_i, line_j, ...)` is what two substitute lines in one region lose together beyond their single-line figures, for the optimiser's `y_ij` terms. The web app's `CannibalisationCallout` and `HaloCallout` read "Promoting A reduces B's units by N% (−₹X profit)" and "…lifts…", showing effects of 1% or more, the top 3 by profit.

## LLM providers

Agents reach an LLM only through `promopilot.llm` (ADR 0001, ADR 0019, ADR 0027). `LLM_PROVIDER` picks the provider:

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` (`.env`) | `replay` | `replay` answers from recorded cassettes and needs no key. `openai` or `anthropic` calls that provider live |
| `LLM_CASSETTE_DIR` (`.env`) | `cassettes` | One JSON file per request hash, relative to `backend/` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` (`.env`) | empty | Needed only for `openai` and `make record-cassettes`. The model must accept `temperature=0`: use `gpt-4.1-mini` (the `gpt-5` reasoning models reject it). Keep the key in `.env`, never commit it |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (`.env`) | empty | Needed only for `anthropic`, or to make Anthropic the fallback when OpenAI is primary. Use `claude-sonnet-5` |
| `LLM_PRICES`, `USD_INR_RATE` (`.env`) | built in | Per-model prices in US dollars per million tokens (JSON), and the rupee rate for per-session cost. The defaults cover `gpt-4.1-mini` and `claude-sonnet-5` |

A live provider retries timeouts, rate limits and server errors up to 3 attempts (waiting 1 s, then 2 s). If it still fails and the other live provider has a key and model, that provider answers instead. Otherwise the API logs `llm_no_fallback` at startup. Every call's tokens are counted per planning session, and the cost is priced from `LLM_PRICES`.

In replay mode, a request with no recorded cassette fails with `CassetteMissError` naming its hash. This usually means a prompt or schema changed and the cassettes need re-recording. Replay never falls back. Cassettes store only the request content, the parsed response and the tokens it was billed for, never headers or keys. Tests use `FakeProvider` or `ReplayProvider` and never call a real LLM. The live smoke checks in `backend/tests/live` are marked `live` and excluded by default. Run them deliberately with keys exported: `uv run pytest -m live tests/live`.

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
| GET | `/api/models` | `{"models": [{model_id, kind, version, trained_at, as_of_week, metrics, live}]}`, newest first. `live` marks the model this API process is serving (ADR 0026) |
| POST | `/api/models/retrain` | Retrain the demand and relations models as `make train` does by default (the as-of week after the history, seed 42). The request stays open while it fits (60 to 110 seconds on the default world), then returns `201` with the new demand entry, which is now the latest and live, as is the new relations version. `409` if a retrain is already running or no data is loaded |
| GET | `/api/competitors/gaps` | Competitor price index, gap and KVI undercut per SKU × region, widest gap first (ADR 0031). Optional filters `region`, `category`, `kvi_only` and `as_of_week` (default: the week after the loaded history). `409` if no data is loaded, `422` for an unknown category |
| GET | `/api/relations/{sku_id}` | `{model: {model_id, version, as_of_week}, sku_id, substitutes: [{sku_id, theta, std_error, q_value}], complements: [{sku_id, lift, support, theta, std_error}]}`; θ is null where not estimable. `404` for an unknown SKU, `503` when no relations model fitted on the live demand model is registered (ADR 0033) |
| GET | `/health`, `/api/health` | Always `200` while the process runs. `/health` is for the container healthcheck; the web app uses `/api/health` through its proxy. `{"status": "ok" \| "degraded", "version", "checks": {"database": "ok" \| "error", "model_registry": "ok" \| "missing"}}`. `status` is `degraded` if the database is unreachable or no demand model is loaded |

In E3 a planning session is a walking skeleton (ADR 0020). A minimal Context agent reads the brief into a planning request: scope, a promo window chosen from the weeks after the as-of week, and a marketing budget in rupees. If any of these is missing, the session fails and the error names it. A naive greedy planner then offers 20% off to All customers on in-scope SKUs, ranked by base margin, within the budget. It has no uplift model yet, so each line's expected incremental profit is minus its promo cost. E4–E8 replace it. The as-of week is the first week after the loaded sales history.

`promopilot.guardrails` holds the E8 checks that need no LLM (ADR 0028):

- `validate_plan(plan, request, policy)` returns a violation for every hard constraint a plan breaks on its own plan-time numbers (ADR 0012). The checks are budget, minimum margin, margin floor, stock, maximum discount, below cost, promo window, maximum promoted SKUs per category per region, and one plan line per SKU per region.
- `check_numeric_grounding(text, tool_outputs)` lists every number in a text that no tool output supports, at the precision the text shows. It reads ₹, lakh, crore and percentages.

The Critic and the Explainer will call them.

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
- [ADR 0023: The baseline trains on clean weeks with horizon-safe features, and the registry pickles artifacts to a volume the api loads from](docs/adr/0023-baseline-forecast-and-model-registry.md)
- [ADR 0024: The promo response is a per-SKU Poisson GLM on a reference-index baseline, shrunk by empirical Bayes](docs/adr/0024-promo-response-glm-with-empirical-bayes.md)
- [ADR 0025: Tools are typed async handlers that return typed errors, and `estimate_demand` resolves the latest model on every call](docs/adr/0025-tool-registry-and-estimate-demand.md)
- [ADR 0026: Retrain holds the request until the new model is live, one at a time, on the default as-of week and seed](docs/adr/0026-models-api-synchronous-retrain.md)
- [ADR 0027: LLM calls take one tool step at a time, retry transient errors, fall back to the other live provider, and are costed per session in a context scope](docs/adr/0027-resilient-llm-layer.md)
- [ADR 0028: Guardrails validate plan facts and ground numbers at the precision the text shows](docs/adr/0028-guardrails-plan-facts-and-grounding-rules.md)
- [ADR 0029: Relations use one pooled cross effect per pair on the demand model's fit, and basket lift confirmed by it](docs/adr/0029-relations-pooled-cross-effects-and-basket-lift.md)
- [ADR 0030: The models page groups versions by kind, times the retrain, and reports its outcome inline](docs/adr/0030-models-page-display-and-retrain-feedback.md)
- [ADR 0031: Competitor gaps compare the last known competitor price with our base price; the KVI tolerance is one-sided; data tools bind the as-of week](docs/adr/0031-competitor-gaps-and-kvi-tolerance.md)
- [ADR 0032: Data tools read at a bound as-of week, pool stock per region, and a deterministic resolver scores brief phrases](docs/adr/0032-data-tools-as-of-source-and-brief-resolution.md)
- [ADR 0033: Cannibalisation and halo per plan line use the oracle's method on fitted inputs, with a pairwise correction for promoted substitutes](docs/adr/0033-cannibalisation-and-halo-per-plan-line.md)

The domain glossary is [CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE)
