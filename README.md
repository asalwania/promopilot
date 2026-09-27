# PromoPilot

Agentic retail promotion planner for the ET AI Hackathon (Problem 3, Retail: Autonomous Promotion Planner). A planning brief in plain English becomes a promotion plan that respects inventory, margin and budget constraints, with every number coming from deterministic tools and a human approving the result.

> **Status:** epic E3 (walking skeleton). `make data` generates the synthetic world. A brief typed on the home page becomes an optimised plan on the session page (ADR 0020, ADR 0038), and the Docker stack does this with no API key (ADR 0022). Real forecasting, optimisation and the full agent arrive in later epics; see [SPEC.md](SPEC.md) §15 for the delivery plan.

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

The **Data** link opens `/data`: products, pooled inventory with overstock flags, and competitor gaps with undercut KVIs, as three cards. Each list loads once; a shared bar filters them by region and category, overstocked SKUs only or undercut KVIs only. Every number's tooltip names the tool it comes from (ADR 0034).

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

The world is tuned so that promotions can pay, not only clearance lines (ADR 0037). Mechanism effects are strong enough to offset the price cut, the post-promotion dip is moderate, and the company-policy fixed marketing cost is ₹500 per line-week (₹750 for BOGO, ₹1,000 for BUNDLE). On the seed-42 Diwali demo brief, short, shallow promotions on regular SKUs earn true incremental profit alongside the clearance lines.

| Setting | Default | Meaning |
|---|---|---|
| `DATA_DIR` (`.env`) | `../data` | Output directory, relative to `backend/` |

For a different world, run `cd backend && uv run python -m promopilot.datagen --config my.yaml --seed 7 --out ../data --load`. The YAML only needs the keys it overrides. The same seed and config always give byte-identical files. Loading is idempotent: the first Alembic migration creates the tables, and every load replaces their rows in one transaction. The app reads them through `promopilot.data.RetailData`, whose time-dependent queries take an explicit as-of week and never return sales, promotions, baskets or competitor prices at or after it (ADR 0008). Only `promopilot.datagen` and `promopilot.evals` may read `data/ground_truth/`.

## Demand model

`make train` fits the baseline demand forecast on the data in Postgres (SPEC §9.1, ADR 0023). By default it uses the as-of week after the history (`--as-of-week` and `--seed`, default 42, override this) and registers a new version. The baseline is LightGBM. It forecasts no-promotion units per store × SKU × segment × week and learns only from weeks free of promotions and their 4-week pull-forward dip. It never sees history at or after the as-of week (ADR 0008). Before the final fit, it is validated on the last 12 weeks: the registry records holdout WAPE at the model grain (`baseline_wape`) and summed to store × SKU and region × SKU. On the seed-42 world these are 0.44, 0.25 and 0.13.

The promo response is fitted on the same history (ADR 0024). A Poisson GLM per SKU estimates:
- own-price elasticity per segment;
- competitor sensitivity, which controls for the competitor price index so the true elasticity is recovered (ADR 0016);
- mechanism effects;
- pull-forward.

Empirical Bayes shrinks each estimate toward its subcategory, and the pull-forward dip is floored at 0 so a promotion never lifts the weeks after it (ADR 0037). `DemandModel.predict(options, context)` takes a batch of plan lines. It returns each one's mean and std of units, its uplift net of pull-forward, and its revenue, gross profit, margin and promo cost. `coefficients()` lists the fitted terms with their standard errors. The registry also records `response_skus_fitted` and `elasticity_median_std_error`. On the seed-42 world the median error of the recovered elasticities is 8.1%. Training takes 40 to 90 seconds.

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

The thresholds live in `RelationsConfig`. The registry records them with the counts and the demand version used. On the seed-42 world, substitute precision/recall is 0.87/1.00 and complement precision/recall is 1.00/0.97.

The API serves the latest relations model only while it was fitted on the live demand model; otherwise `get_relations` answers `model_unavailable` and `GET /api/relations/{sku_id}` answers `503` (ADR 0033). The `get_relations` tool takes 1 to 50 SKU ids and returns each one's substitutes and complements with the model's id and version.

**Cannibalisation and halo** (ADR 0033). `line_effects(lines, relations, demand_model, products)` returns one row per plan line and each SKU it moves in its region, in scope or not (ADR 0005). Each row has the SKU's baseline units, the change in units and in percent, the change in profit at its base margin, and that change as cannibalised or halo profit. A detected relation moves units by baseline × (exp(Σ θ·log(p_eff/base)) − 1) over the promo weeks and targeted segments. `pairwise_cannibalisation(line_i, line_j, ...)` is what two substitute lines in one region lose together beyond their single-line figures, for the optimiser's `y_ij` terms; `pairwise_cannibalisations(pairs, ...)` computes a whole batch at once, vectorised across pairs (ADR 0036, ADR 0039). The web app's `CannibalisationCallout` and `HaloCallout` read "Promoting A reduces B's units by N% (−₹X profit)" and "…lifts…", showing effects of 1% or more, the top 3 by profit.

## Promo options

`promopilot.optimizer.generate_options(request, context)` enumerates every promo option for a planning request (SPEC §9.3, ADR 0035). For each in-scope SKU and region it lists mechanism × depth × duration × start week × target segment. PCT_OFF and FIXED_PRICE use 5–50% depths, BOGO uses 50% only, and BUNDLE uses 10–25% with each detected complement as its partner, in scope or not. Every duration from 1 to 4 weeks is tried at every start week that fits inside the promo window, for each of the four segments and for All customers. Before prediction it prunes options deeper than the policy maximum discount, options that sell the anchor or partner below unit cost (unless that SKU is overstocked in the region), and FIXED_PRICE depths that land on a charm price a shallower depth already offers. It predicts the rest in one batch. It then prunes options whose P90 units (mean + 1.2816 × std) exceed the anchor's pooled available stock, or the partner's. Each survivor carries its predictions, cannibalisation and halo, and clearance value. The result is a frozen `PromoOptions`: the plan lines, a table with one row per line, the enumerated count, and the pruned count per reason.

The `generate_candidates` tool takes a planning request plus optional mechanisms, target segments and SKU ids. It keeps the full set in an in-process `CandidateStore` and returns a summary: counts, pruned counts per reason, counts per region and mechanism, the top 20 options by value, and a `candidate_set_id` for the optimiser. On the seed-42 demo brief (Snacks and Beverages, North and West, Diwali weeks 108–109) it enumerates 28,980 options, keeps 10,396 and takes about 7 s. About 1,900 of them have positive value, some 500 of those without clearing overstock (ADR 0037).

## Optimiser

`promopilot.optimizer.solve(request, options, facts, policy, *, settings, seed)` selects the promo plan from a candidate set with OR-Tools CP-SAT (SPEC §9.4, ADR 0036). It maximises the objective in integer paise: the selected options' values less what selected substitute pairs lose together (ADR 0005, ADR 0033). The plan has:

- at most one plan line per SKU per region, a BUNDLE's partner included (ADR 0014);
- total promo cost within the marketing budget;
- a blended margin at or above the minimum margin, never below the policy margin floor (ADR 0007);
- at most 10 promoted SKUs per category per region, a partner counting in its own category.

Only options worth at least a paisa alone, which keep every per-line rule (stock, window, maximum discount, below cost), are eligible. The result carries the status (`OPTIMAL`, `FEASIBLE` when the time limit ran out first, `INFEASIBLE`), the objective, the plan, and the selected rows of the candidate table. It also explains the plan (ADR 0038):

- **Binding constraints**: the budget, the margin (`minimum_margin` from the brief, or the policy `margin_floor`) and each promoted-SKU cap per category and region, where dropping it gives a strictly better objective. A constraint no plan could fill is ruled out at once. A better plan one swap away from the optimum proves one binds; otherwise it is re-solved without it for a better plan that breaks it, stopping at the first found, within a shared time limit. Its evidence is `exact`, `lower_bound` (a better plan was found, not the best) or `unproven` (time ran out first). On the seed-42 demo brief the budget and both Beverages caps are proven binding in well under a second; proving that the margin and the Snacks caps do not bind takes about 4 s each, so with the default limit they stay `unproven` (all six settle with 30 s).
- **Why chosen**, per plan line: the positive parts of its value (`incremental_profit`, `clearance_value`, `halo`) in rupees, its value, and whether it is the best eligible option for its SKU and region.
- **Not selected**: the best option of up to 5 SKUs and regions with no plan line, best value first, with every rule it breaks alone or added to the plan: `low_uplift`, `out_of_stock`, `breaks_policy`, `over_budget`, `breaks_margin`, `max_promoted_skus`, `cannibalises` (naming the plan lines' SKUs).

The `run_optimizer` tool takes the `candidate_set_id` from `generate_candidates`. It returns the status, the objective, each selected line with its numbers and why it was chosen, the plan's totals, the binding constraints and the not-selected list. The solver is deterministic: one worker and a fixed seed by default, and interleaved search with more workers. It is configured by:

| Setting | Default | Meaning |
|---|---|---|
| `OPTIMIZER_TIME_LIMIT_SECONDS` | `10` | Wall-clock limit per solve |
| `OPTIMIZER_WORKERS` | `1` | CP-SAT workers |
| `OPTIMIZER_SEED` | `0` | CP-SAT random seed |
| `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS` | `8` | Wall-clock seconds for proving which constraints bind, on top of the solve (outside its 10 s budget); a constraint left unsettled is `unproven` |

On the seed-42 demo brief, 1,935 options are eligible with 3,796 pairwise terms. The optimal plan has 35 lines, 21 of them without clearance, worth ₹172,384 for ₹199,909 of the ₹2 lakh budget. The oracle scores it at +₹66,607 incremental profit and ₹86,654 clearance value (ADR 0037). Solving takes about 6–7 s, within SPEC's 10 s optimiser budget: about 4.5 s is CP-SAT and about 2 s is pricing the 415,524 candidate pairs, which is vectorised (ADR 0039). Generating the candidates first takes another 7–9 s, which is timed separately and tracked in #113. A `model`-marker test asserts that `solve` stays under 10 s on the fitted seed-42 world.

## Mechanism comparison

`promopilot.mechanisms.compare(sku_id, region, context, *, chosen=None)` compares the mechanisms for one SKU in one region (SPEC F-02, ADR 0041). The `ComparisonContext` is a generated candidate set, the relations model and the products. For each mechanism it picks the option with the highest value (incremental profit − cannibalisation + halo + clearance value, the optimiser's per-option objective) over every depth, duration, start week and target segment the candidate set kept. Each outcome carries the option, its effective price from `promopilot.economics` (BOGO 50% off, a FIXED_PRICE charm price ending in 9, a BUNDLE at the depth off each SKU's own base price, which is the pair's discount split pro-rata), and its expected units, revenue, gross profit, margin, promo cost, incremental profit, cannibalisation, halo, clearance value and value. A BUNDLE names its anchor, its partner and the pair's basket lift. It is compared only when the SKU has a detected complement. Mechanisms are ranked by value, highest first. A mechanism whose every option broke a per-line rule is listed last, with the rules (for example BOGO `below_cost` on a SKU that is not overstocked). `chosen`, a plan line, stands for its own mechanism instead of that mechanism's best option. The numbers are the demand model's expected values; simulator bands can join them after #39.

The `compare_mechanisms` tool takes a planning request, a SKU id and a region in the request's scope. It generates that SKU and region's options, as `generate_candidates` would, and returns the comparison with the models' versions and the as-of week. It needs no candidate set. The planning session compares every plan line on the options it already generated, and stores the comparison on the line (`mechanism_comparison`).

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

`make record-cassettes` reads each brief into a planning request through OpenAI and records every LLM request. Planning after that calls no LLM, so recording needs no trained model (ADR 0038). It replaces the cassettes only if every brief becomes a planning request. If one fails, it names the brief, exits non-zero and changes nothing. A full run removes stale cassettes, so commit the whole directory (ADR 0022).

## API

| Method | Path | Response |
|---|---|---|
| POST | `/api/sessions` | Start a planning session from `{"brief": "..."}` (1–2000 characters, not blank; otherwise `422`). Returns `202 {"session_id"}` at once; planning runs in the background |
| GET | `/api/sessions/{id}` | `{session_id, status, brief, planning_request, plan_revision, error}`; `404` if unknown. `status` is `planning`, then `awaiting_approval` with plan revision 1, or `failed` with an `error` saying why. The revision has `solver_status`, `objective`, `binding_constraints`, `not_selected`, and `why_chosen` and `mechanism_comparison` on each line (ADR 0038, ADR 0041) |
| GET | `/api/models` | `{"models": [{model_id, kind, version, trained_at, as_of_week, metrics, live}]}`, newest first. `live` marks the model this API process is serving (ADR 0026) |
| POST | `/api/models/retrain` | Retrain the demand and relations models as `make train` does by default (the as-of week after the history, seed 42). The request stays open while it fits (60 to 110 seconds on the default world), then returns `201` with the new demand entry, which is now the latest and live, as is the new relations version. `409` if a retrain is already running or no data is loaded |
| GET | `/api/catalog/products` | `{"products": [{sku_id, name, brand, category, subcategory, pack_size, base_price, unit_cost, is_kvi}]}` in SKU order (ADR 0034). Optional filters `category` and `kvi_only`. `422` for an unknown category |
| GET | `/api/catalog/regions` | `{"regions": [{region, stores: [{store_id, city, segment_mix}]}]}` |
| GET | `/api/inventory` | Stock per SKU × region pooled over the region's stores, as `get_inventory_status` computes it, with name, category and overstock flag (ADR 0032, ADR 0034). Optional filters `region`, `category`, `overstocked_only` and `as_of_week` (default: the week after the loaded history). `409` if no data is loaded for the week, `422` for an unknown category or a region without stores |
| GET | `/api/competitors/gaps` | Competitor price index, gap and KVI undercut per SKU × region, widest gap first (ADR 0031). Optional filters `region`, `category`, `kvi_only` and `as_of_week` (default: the week after the loaded history). `409` if no data is loaded, `422` for an unknown category |
| GET | `/api/relations/{sku_id}` | `{model: {model_id, version, as_of_week}, sku_id, substitutes: [{sku_id, theta, std_error, q_value}], complements: [{sku_id, lift, support, theta, std_error}]}`; θ is null where not estimable. `404` for an unknown SKU, `503` when no relations model fitted on the live demand model is registered (ADR 0033) |
| GET | `/health`, `/api/health` | Always `200` while the process runs. `/health` is for the container healthcheck; the web app uses `/api/health` through its proxy. `{"status": "ok" \| "degraded", "version", "checks": {"database": "ok" \| "error", "model_registry": "ok" \| "missing"}}`. `status` is `degraded` if the database is unreachable or no demand model is loaded |

A minimal Context agent reads the brief into a planning request (ADR 0020): scope, a promo window chosen from the weeks after the as-of week, and a marketing budget in rupees. If any of these is missing, the session fails and the error names it. The optimising planner then generates every promo option on the latest demand model and the live relations model, and the optimiser selects plan revision 1 with its status, binding constraints, not-selected list and a "why chosen" per line (ADR 0038). Each line also carries a comparison of the mechanisms for its SKU and region (ADR 0041). With no trained model the session fails and says to run `make train`. On the seed-42 demo brief planning takes about 25 s: about 9 s generating the options (#113), about 6 s solving and 8 s proving binding constraints. E8's agent graph replaces this fixed pipeline. The as-of week is the first week after the loaded sales history.

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
- [ADR 0034: The data explorer loads flat lists once, filters them in the browser, and names each number's source tool](docs/adr/0034-data-explorer-and-catalogue-endpoints.md)
- [ADR 0035: Promo options are enumerated in full, pruned before and after one batch prediction, and handed to the optimiser through an in-process store](docs/adr/0035-promo-option-generation.md)
- [ADR 0036: The CP-SAT optimiser selects from positive-value options, charges exact pairwise terms, and runs single-threaded with a fixed seed](docs/adr/0036-cp-sat-optimiser.md)
- [ADR 0037: Promotions can pay in the synthetic world: stronger mechanism effects, a smaller pull-forward dip floored at 0 when fitted, ₹500 fixed cost per line-week](docs/adr/0037-demo-world-promo-economics.md)
- [ADR 0038: Planning sessions use the optimiser, with proven binding constraints and structured reasons for each plan line and each rejected option](docs/adr/0038-sessions-use-the-optimiser.md)
- [ADR 0041: Mechanisms are compared on the candidate set's expected numbers, by value, with the plan line standing for its own mechanism](docs/adr/0041-mechanism-comparison.md)

The domain glossary is [CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE)
