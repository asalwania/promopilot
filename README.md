# PromoPilot

Agentic retail promotion planner for the ET AI Hackathon (Problem 3, Retail: Autonomous Promotion Planner). A planning brief in plain English becomes a promotion plan that respects inventory, margin and budget constraints, with every number coming from deterministic tools and a human approving the result.

> **Status:** epic E3 (walking skeleton). `make data` generates the synthetic world. A brief typed on the home page becomes an optimised plan on the session page (ADR 0020, ADR 0038), and the Docker stack does this with no API key (ADR 0022). Real forecasting, optimisation and the full agent arrive in later epics; see [SPEC.md](SPEC.md) §15 for the delivery plan.

## Try it: `make demo`

Prerequisites: Docker (Docker Desktop on Windows and macOS) and GNU make. On Windows, run `make` from **Git Bash**, or use the plain Docker command below. No API key and no other tools are needed.

```bash
git clone https://github.com/asalwania/promopilot.git
cd promopilot
make demo
```

Open http://localhost:3000 when it prints `PromoPilot is ready`. `make demo` (ADR 0073):

1. builds the api and web images;
2. starts Postgres;
3. runs the **init** step in the foreground, which:
   - generates the seed-42 synthetic world and loads it into Postgres;
   - trains and registers the demand and relations models into a Docker volume;
   - prints each step, an estimate and its time;
4. starts the api and web app and waits until both are healthy;
5. prints which LLM answers.

The first start takes about 5 minutes on a CI-class machine: roughly 1.5 minutes to build, 1 to load the data and 1.5 to train. It can take 5–10 minutes on a laptop's first Docker build, or with a slow network. Later runs reuse the data and models: the init step prints `already loaded: skipped` and `already trained: skipped`, and the stack is up in well under a minute.

**Without an API key (demo mode)** the api replays the LLM calls recorded in `backend/cassettes/`. The home page shows a **Demo mode** badge. Its four example briefs replay exactly as recorded, including the recorded amendments, answer, accepted relaxation and approval their cards suggest.

A brief of your own, or an example with constraints added, is not in the demo recordings. It still plans, but without the language model: rules read the brief, the default sequence plans and a template explains. The composer and the session page say so in a **Not in the demo recordings** note, not an error.

**With an API key** the same command plans any brief live. Put the key in `.env` (copy `.env.example` first), then run `make demo` again:

```bash
OPENAI_API_KEY=sk-...      # OPENAI_MODEL defaults to gpt-4.1-mini
# or ANTHROPIC_API_KEY=... # ANTHROPIC_MODEL defaults to claude-sonnet-5
```

The badge then reads **Live LLM** with the provider and model. The stack's `LLM_PROVIDER` is `auto` in demo mode: OpenAI if its key is set, else Anthropic, else replay. `make up` always replays, whatever `.env` holds.

The `/evals` page shows the recorded full eval run baked into the api image (32 scenarios, `backend/evals/published/`).

| Command | What it does |
|---|---|
| `make demo` | Build, prepare (or reuse) the data and models, start the app, print the URL |
| `make demo-down` | Stop the demo, keeping its data, models and sessions for a fast restart |
| `make demo-reset` | Stop the demo and delete its data, models and sessions. Run it after pulling a change to the data generator |

**Without make** (for example in Windows PowerShell), the same stack starts with:

```bash
docker compose --profile demo up --build   # add -d to run it in the background
```

The init step's progress shows in the log. For live mode this way, also set `STACK_LLM_PROVIDER=auto` in `.env`.

**Troubleshooting**

- A port already in use: set `WEB_PORT`, `API_PORT` or `POSTGRES_PORT` in `.env`. The defaults are 3000, 8000 and 5432.
- The init step failing prints its reason and stops before the api starts. `make demo-reset`, then `make demo` starts over.
- On Windows, `make` must run from Git Bash, because the Makefile refuses PowerShell and cmd.exe.

## Quickstart (development)

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 24 with [pnpm](https://pnpm.io/) 11, GNU make. On Windows, run `make` from **Git Bash**.

```bash
git clone https://github.com/asalwania/promopilot.git
cd promopilot
make setup   # creates .env from .env.example, installs backend + frontend deps, git hooks
make dev     # Postgres in Docker; API on :8000 and web on :3000 with hot reload
```

Open http://localhost:3000. Click **Try it** on one of the four example briefs, or type your own, and click **Plan it**. Each example is word for word a recorded session script, so it replays with no API key. The optional **Constraints** form (marketing budget, minimum margin, regions, categories, a holiday for the promo window, a clearance target) adds one sentence per constraint after the brief, and the page shows the exact text it will send. Picking an example clears the form, so the example replays as recorded (ADR 0058). The app starts a planning session and opens `/sessions/<id>`. That page polls the session every second while it is `planning`. It then shows the plan, or the reason the session failed (ADR 0021). The plan opens with the Explainer's summary, then a tab per region: each plan line's mechanism, depth, start, duration and segment, its uplift over the no-promotion baseline, its simulated profit range (P10–P90) and stock-out risk, its promo cost and expected incremental profit, with badges for cannibalisation, halo and a competitor undercut. Money reads as the rationales do: rupees below ₹1 lakh, then lakh or crore. Every number names the tool it came from in a tooltip. **Details** opens a line's rationale, its uplift by customer segment and its callouts; **Mechanisms** opens a drawer comparing each mechanism's best option for the SKU and region, with a bundle suggestion (the pair, basket lift and expected incremental profit) where one exists. **Compare regions** puts each SKU's regional lines side by side (ADR 0060). An **Assumptions** panel lists how the agent read the brief: every field with its value, its source (from the brief, from data, or a default) and its confidence. Readings below 90% confidence, flagged values such as a brief value company policy overrode (with the reason), and readings made by rules while the language model was down stand out, and the panel says how many need a look. When the agent asks instead of guessing, its questions appear as a form: each has an answer box, its reason (missing, low confidence or ambiguous) and suggestions that fill the box. **Answer and resume planning** sends every answer to `POST /clarify`, and the page goes back to planning at once. A question asked again shows the earlier answer (ADR 0061). While a plan revision waits for a decision, a **Review plan revision N** card under the status offers **Approve** (after a confirm; an infeasible revision cannot be approved), **Reject** (with a required reason) and an **Amend the brief** box. **Amend and re-plan** sends the text to `POST /amend`, and the page goes back to planning at once, still showing the amended revision. A rejected revision can only be amended. An amended revision's plan opens with **What changed from plan revision N**: the Explainer's change explanation, the planning-request changes, the objective and promo cost before and after, and the plan lines added, removed and changed. An approved session is marked **Final** and offers no more actions, and an **Audit trail** lists every amendment, approval and rejection with its time (ADR 0066). After the plan, a **Constraint checklist** gives pass or fail for the budget, minimum margin, stock, clearance and company policy, read from the violations the Critic left open: a failed row lists them, a passed row names the limit it was checked against, and brief values company policy overrode are noted on the policy row. A **Not selected** card lists the best options the optimiser left out, best first, with each one's value alone and why it was left out. An infeasible revision (any revision short of a clearance target, ADR 0074) opens with its clearance shortfalls, binding constraints and the proposed relaxation (each change from the brief's value, its size and what policy allows), and **Accept the relaxation and re-plan** sends `POST /amend {accept_relaxation: true}` in one click (ADR 0067). A **Competitor prices** card lists the KVI prices in the brief's scope that the planner saw, undercuts first and flagged, with our price, the competitor's, the gap and CPI, the plan line promoting each KVI (or "Not promoted"), and the planner's response to the undercuts. A **Simulation** card charts each plan line's P10–P90 band and P50 for gross profit, units or promo spend, for all regions or one, with the plan's totals and each region's stock-out risk; **Show values** lists the charted ranges. While a revision waits for a decision, **Re-simulate** stress-tests it with a competitor match probability (no reaction, 25%, 50% or 100%) through `POST /api/plans/<id>/simulate`: the result replaces the stored simulation, the plan table's ranges with it, and the card and plan say which competitor reaction they show. A final plan's simulation is read-only (ADR 0068). Beside it, a live **agent trace** streams every step from `/api/sessions/<id>/events`: each node run (Context agent, Planner and its attempts, Critic, Explainer, Approval) with its tool calls, decisions, findings, clarification questions and LLM calls. After a network blip it resumes where it left off, with no event shown twice. An **LLM usage** meter shows the session's calls, tokens and cost in rupees and dollars (ADR 0057). The home page also fetches `/api/health` from its own origin and shows the database status.

The **Models** link in the header opens `/models`. It lists every registered model version, one table per kind, with its training time, as-of week and metrics, and marks the live one. **Retrain** calls `POST /api/models/retrain` and shows the elapsed time until the new version is live, then reloads the list; a failure shows the API's reason (ADR 0030).

The **Data** link opens `/data`: products, pooled inventory with overstock flags, and competitor gaps with undercut KVIs, as three cards. Each list loads once; a shared bar filters them by region and category, overstocked SKUs only or undercut KVIs only. Every number's tooltip names the tool it comes from (ADR 0034).

The **Evals** link opens `/evals`, the latest [eval report](#evals) from `GET /api/evals/latest`:
- **The header** says when the report was generated, with which provider, on which world, and how many scenarios and runs.
- **Metric cards**, in five groups (constraints, agent behaviour, plan quality, model recovery, latency and cost), show each value against its SPEC §12.2 target with the report's own **Pass** or **Fail**. A metric with no target is **Reported**, with its aim if it has one, and one with nothing scored reads n/a.
- **A regret chart** puts every scored run's regret in order against the median and the target. The axis stops at ±100%, and **Show values** lists the exact values.
- **A scenario table** gives one row per scenario with its result and its last run's outcome, constraints, oracle breaches, properties, standing against the baseline, regret, time and cost, and warns of fallbacks and cassette misses. It can be filtered to the failed scenarios or to one group.
  - **Details** opens each run's trace as the report holds it: the route, questions, fallbacks, cassette misses, plan, oracle objectives, violations and properties, with a link to the scenario's YAML. Eval sessions are never stored, so there is no session page to open.

Before any run the page says to run `make eval` (ADR 0072). The Docker stack (`make demo` and `make up`) serves the recorded full run baked into the api image (ADR 0073).

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

`make demo` does all of this in one command (see [Try it](#try-it-make-demo)). The Docker stack needs no API key. Under `make up` Compose runs the api with `LLM_PROVIDER=replay` and the cassettes baked into its image, whatever `.env` says (ADR 0022). Under `make demo` it replays unless `.env` holds a key (ADR 0073). CI's `demo` job runs `make demo` from a clean checkout, replays every recorded session from the cassettes alone (`python -m promopilot.cassettes --check`, ADR 0054), then Playwright types the `e2e` brief from `backend/cassettes/sessions.json`, clicks **Plan it**, waits for the plan, checks the region tabs, a source tooltip, a line's details and its mechanism drawer, the West tab and the side-by-side view, checks the constraint checklist and the not-selected list, checks the competitor prices (an undercut and the planner's response) and the simulation chart, then re-simulates with a 50% competitor match probability and checks the stress-test label and the stored reaction (ADR 0068; re-simulating makes no LLM call), checks that the live trace shows the agent's node runs, tool calls and Critic decision and that the usage meter counts the replayed calls, and checks that the Explainer's recorded answer explains the plan. A second journey types the `clarify` brief, sees the budget question and the assumptions panel, answers with the recorded answer and waits for the plan (ADR 0061). A third journey plans the `demo` brief and amends it with its two recorded amendments, checking each revision's diff. The demo's first three revisions are infeasible, so it checks that they cannot be approved, and that revision 1 shows its binding clearance target, its relaxation and the accept button, and a failing clearance check (ADR 0067). It then clicks **Accept the relaxation and re-plan** on revision 3, sees revision 4's diff with the clearance-target change, approves it and sees the session **Final**, with every amendment (the accepted relaxation badged) and the approval on the audit trail (ADR 0070). Two more plan the `e2e` brief and approve it (the session becomes final) or reject it with a reason (the session stays open for an amendment) (ADR 0066); the approved one keeps its simulation chart with no **Re-simulate** (ADR 0068). Another types a brief of its own and sees the **Demo mode** badge and the **Not in the demo recordings** note, before and after **Plan it**, with no error, and `/evals` shows the baked report. The job then runs `make demo` again and checks that the init step skipped both the data and the models (ADR 0073).

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install dependencies and pre-commit hooks |
| `make dev` | Postgres in Docker; API and web natively with hot reload |
| `make up` / `make down` | Full stack (postgres, api, web) in Docker |
| `make test` | Backend + frontend unit/API tests (no Docker, no LLM). Fails if line coverage of the core packages (datagen, models, optimizer, simulator, agents, economics, domain) is below 85% |
| `make test-integration` | Backend tests against a throwaway Postgres (testcontainers) |
| `make test-e2e` | Playwright against a running stack with data loaded: health, brief to plan table with the live trace, a clarifying question answered through to a plan, the demo amended twice with its diffs, and a plan approved and one rejected |
| `make lint` / `make format` | ruff, ESLint, Prettier |
| `make typecheck` | mypy strict, tsc strict |
| `make api-types` | Export OpenAPI to `docs/openapi.json`, regenerate the frontend types and the [API reference](docs/api.md) |
| `make api-docs` | Regenerate only the [API reference](docs/api.md) from the committed `docs/openapi.json` |
| `make data` | Generate the seeded synthetic dataset into `data/generated/` (Parquet) and its hidden ground truth into `data/ground_truth/`, then load the tables into Postgres (starts it if needed) |
| `make record-cassettes` | Record every scripted session's LLM calls with a live OpenAI key; `ONLY=name` re-records one session (see [Recording cassettes](#recording-cassettes)) |
| `make check-cassettes` | Replay every scripted session through the full agent graph from the cassettes alone, with no key |
| `make train` | Fit the demand model, then the relations model, on the loaded data (`make data` first) and register both (see [Demand model](#demand-model) and [Relations](#relations)) |
| `make eval` | Play the eval scenarios on their own seeded world and write the report to `backend/evals/reports/`; `ONLY="a b"`, `SMOKE=1`, `RUNS=n`, `SEED=n` (see [Evals](#evals)). Needs no Docker, `make data` or `make train` |
| `make eval-smoke` | What CI runs: replay the five smoke scenarios with no key and fail on a session with no plan, a broken constraint or expected property, or any cassette miss (see [Smoke eval in CI](#smoke-eval-in-ci)) |
| `make record-eval-cassettes` | Play the eval scenarios with a live OpenAI key and record what no cassette holds into `backend/evals/cassettes/`; `ONLY="a b"` records some. Costs money (see [Evals](#evals)) |
| `make demo` / `make demo-down` / `make demo-reset` | The one-command demo in Docker, with no API key: seed-42 data, trained models and the app; stop it keeping its volumes; or delete them (see [Try it](#try-it-make-demo)) |

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

`promopilot.agents.resolution.BriefResolver` maps a brief's phrases to catalogue entities with no LLM: "Snacks and Beverages" to categories, "North and West" to regions, "400g namkeen packs" to exactly the Namkeen 400g SKUs, and "Diwali" to the weeks the calendar labels Diwali after the as-of week. "All regions", "pan-India" or "nationwide" is every region, and "all categories" or "the entire range" every category (ADR 0053). `mentions(text)` lists the regions, categories, product names and holidays a whole text names exactly, for the Context agent's fallback reading. Each candidate has a match score from 0 to 1 (1.0 only for an exact match). A resolution is ambiguous when its best score is below 0.7 or a runner-up is within 0.1 of it, so the Context agent can ask instead of guess.

## Relations

`make train` and retrain fit the relations model after the demand model, on the same history, and register it as its own kind (SPEC §9.2, ADR 0029). `promopilot.models.relations.fit(history, baskets, demand_model, as_of_week, seed)` returns `substitutes(sku)`, `complements(sku)` with lift and support, and `cross_effect(i, j)` with a standard error.

- **Substitutes**: for each within-subcategory pair, one pooled Poisson GLM on top of the demand model's fit estimates a symmetric cross-price effect θ. A pair is kept if its Benjamini–Hochberg q across all tested pairs is below 0.05 and θ ≥ 0.1 (ADR 0013).
- **Complements**: basket lift above 1.5, where at least 0.1% of baskets hold both SKUs. Where θ is estimable, the pair must also have θ < 0 with q < 0.05.

The thresholds live in `RelationsConfig`. The registry records them with the counts and the demand version used. On the seed-42 world, substitute precision/recall is 0.87/1.00 and complement precision/recall is 1.00/0.97.

The API serves the latest relations model only while it was fitted on the live demand model; otherwise `get_relations` answers `model_unavailable` and `GET /api/relations/{sku_id}` answers `503` (ADR 0033). The `get_relations` tool takes 1 to 50 SKU ids and returns each one's substitutes and complements with the model's id and version.

**Cannibalisation and halo** (ADR 0033). `line_effects(lines, relations, demand_model, products)` returns one row per plan line and each SKU it moves in its region, in scope or not (ADR 0005). Each row has the SKU's baseline units, the change in units and in percent, the change in profit at its base margin, and that change as cannibalised or halo profit. A detected relation moves units by baseline × (exp(Σ θ·log(p_eff/base)) − 1) over the promo weeks and targeted segments. `pairwise_cannibalisation(line_i, line_j, ...)` is what two substitute lines in one region lose together beyond their single-line figures, for the optimiser's `y_ij` terms; `pairwise_cannibalisations(pairs, ...)` computes a whole batch at once, vectorised across pairs (ADR 0036, ADR 0039). The web app's `CannibalisationCallout` and `HaloCallout` read "Promoting A reduces B's units by N% (−₹X profit)" and "…lifts…", showing effects of 1% or more, the top 3 by profit.

## Promo options

`promopilot.optimizer.generate_options(request, context)` enumerates every promo option for a planning request (SPEC §9.3, ADR 0035). For each in-scope SKU and region it lists mechanism × depth × duration × start week × target segment. PCT_OFF and FIXED_PRICE use 5–50% depths, BOGO uses 50% only, and BUNDLE uses 10–25% with each detected complement as its partner, in scope or not. Every duration from 1 to 4 weeks is tried at every start week that fits inside the promo window, for each of the four segments and for All customers. Before prediction it prunes options deeper than the policy maximum discount, options that sell the anchor or partner below unit cost (unless that SKU is overstocked in the region), and FIXED_PRICE depths that land on a charm price a shallower depth already offers. It predicts the rest in one batch. It then prunes options whose P90 units (mean + 1.2816 × std) exceed the anchor's pooled available stock, or the partner's. Each survivor carries its predictions, cannibalisation and halo, and clearance value. The result is a frozen `PromoOptions`: the plan lines, a table with one row per line, the enumerated count, and the pruned count per reason.

A SKU the brief names for clearance must be in scope and counts as overstocked in every scope region, so it may sell below cost and earns clearance value (ADR 0014). Its options, as anchor or BUNDLE partner, carry their uplift over the promo window, net of the pull-forward dip inside it, and `PromoOptions.clearance` holds each target's window baseline and available stock. A KVI the competitor undercuts gets a **price match**: PCT_OFF at the smallest whole-percent depth that reaches the competitor's price, listed in `PromoOptions.price_matches` (ADR 0040).

The `generate_candidates` tool takes a planning request plus optional mechanisms, target segments, SKU ids to keep (`sku_ids`) and SKU ids to leave out (`exclude_sku_ids`, in every region; not a clearance target of the brief, ADR 0059). It keeps the full set in an in-process `CandidateStore` and returns a summary: counts, pruned counts per reason, counts per region and mechanism, the price matches offered, the top 20 options by value, and a `candidate_set_id` for the optimiser. The id is deterministic: the same call on models fitted through the same week gets the same id, whatever their version numbers, so a recorded planner round replays on a freshly trained registry (ADR 0049, ADR 0054). On the seed-42 demo brief (Snacks and Beverages, North and West, Diwali weeks 108–109) it enumerates 29,025 options, 45 of them price matches for the three KVIs undercut in the North (13–14% off), keeps 10,435 and takes about 7–12 s. About 1,900 of them have positive value, some 500 of those without clearing overstock (ADR 0037).

## Optimiser

`promopilot.optimizer.solve(request, options, facts, policy, *, settings, seed)` selects the promo plan from a candidate set with OR-Tools CP-SAT (SPEC §9.4, ADR 0036). It maximises the objective in integer paise: the selected options' values less what selected substitute pairs lose together (ADR 0005, ADR 0033). The plan has:

- at most one plan line per SKU per region, a BUNDLE's partner included (ADR 0014);
- total promo cost within the marketing budget, and within each regional budget cap the brief sets;
- a blended margin at or above the minimum margin, never below the policy margin floor (ADR 0007);
- at most 10 promoted SKUs per category per region (fewer if the brief says so), a partner counting in its own category;
- each clearance target: a SKU the brief names for clearance sells at least the target share of its available stock over the promo window, in every scope region;
- when the brief or company policy turns it on, no KVI promo price more than the tolerance above the competitor's (ADR 0031);
- no two **strong substitutes** promoted together (ADR 0075): SKUs the relations model detects as substitutes with an estimated θ of at least company policy's `strong_substitute_min_theta` (0.35) never run in one region with a promo week and a target segment in common (All customers shares every segment), a BUNDLE's partner included. It reads the model's estimates, never the ground truth, and is always on: company policy, never relaxed. The model's θ runs about a fifth below the generator's, so 0.35 keeps apart the pairs the eval calls strong (true θ at least 0.5).

A brief may only tighten company policy: `guardrails.plan_limits` applies its values and returns a **policy finding** for each one that would loosen policy, which is kept instead (ADR 0007). Only options worth at least a paisa alone, or that sell towards a clearance target, and that keep every per-line rule (stock, window, maximum discount, below cost, no BUNDLE of two strong substitutes), are eligible. With clearance targets the solve has two phases (ADR 0040): first the plan closest to every target (the stock left short, weighted by unit cost), then the best plan with each target lowered to what that plan reaches. A reachable target is met exactly as a hard constraint; an unreachable one gives the closest plan and a **clearance shortfall** saying by how much it misses, which `validate_plan` also reports. The result carries the status (`OPTIMAL`, `FEASIBLE` when the work budget ran out first, `INFEASIBLE` when no plan found reaches every clearance target), the objective, the plan, and the selected rows of the candidate table. It also explains the plan (ADR 0038):

- **Binding constraints**: the budget, each regional cap, the margin (`minimum_margin` from the brief, or the policy `margin_floor`), each promoted-SKU cap per category and region, each clearance target per SKU and region, the KVI price tolerance, and the strong-substitute rule (`strong_substitutes`, company policy, its limit the θ threshold), where dropping it gives a strictly better objective. A constraint no plan could fill is ruled out at once. A better plan one swap away from the optimum proves one binds; otherwise it is re-solved without it for a better plan that breaks it, stopping at the first found, within a shared time limit. Its evidence is `exact`, `lower_bound` (a better plan was found, not the best) or `unproven` (time ran out first). On the seed-42 speed-test brief (₹2 lakh) the budget, both promoted-SKU caps and the strong-substitute rule are proven binding, and every constraint settles within the default budget: the strong-substitute groups make each re-solve small (ADR 0075).
- **Why chosen**, per plan line: the positive parts of its value (`incremental_profit`, `clearance_value`, `halo`) in rupees, the units it adds towards a clearance target (`clearance_target`), its value, and whether it is the best eligible option for its SKU and region.
- **Not selected**: the best option of up to 5 SKUs and regions with no plan line, best value first, with every rule it breaks alone or added to the plan: `low_uplift`, `out_of_stock`, `breaks_policy`, `over_budget`, `over_regional_budget`, `breaks_margin`, `max_promoted_skus`, `misses_clearance_target`, `breaks_kvi_tolerance`, `strong_substitute` (it would run with a plan line's strong substitute), `cannibalises`. `cannibalises` names the plan lines' SKUs behind either of the last two.

An **infeasible** request is one no plan can reach every clearance target of within its other constraints. Nothing else can make a request infeasible, since the empty plan keeps every other constraint (ADR 0044). A plan that misses a target is always `INFEASIBLE`, never `FEASIBLE` (ADR 0074). When phase 1 runs out of work short of a target, a check with every target hard and no objective settles it, on up to half the relaxation budget: it proves the request infeasible, or finds a plan that reaches every target, and then the targets stay the brief's. When the check runs out of work too, the status is still `INFEASIBLE` and the relaxation's `proven` is false. Without clearance targets, a solve that finds nothing but the empty plan in time returns the **greedy plan**: options best value first, each kept when it keeps every constraint, one line per SKU and region and the strong-substitute rule, and gains net of its pairwise terms, as `FEASIBLE` (ADR 0074). The result keeps the closest plan and its shortfalls, and adds a **relaxation**: the smallest change to the brief's own constraints that makes the request feasible, found by re-solving with slack on those constraints only:

- the marketing budget and each regional cap, up;
- the brief's minimum margin, down in 0.5-point steps to the company-policy margin floor;
- a promoted-SKU cap the brief tightened, up to policy's;
- a KVI price tolerance the brief turned on, off (or back to policy's, where policy turns it on);
- each clearance target (one per SKU, applying in every region), down or dropped.

Each change is weighed as a share of the brief's value: ₹2 lakh → ₹2.2 lakh and 50% → 45% sell-through both count 10%. The relaxation minimises their sum. The values reported are what the plan found actually needs, to the paisa or basis point. Company policy is never relaxed, and scope is not a slack. A first re-solve frees every brief constraint but the targets as far as policy allows. If a target must still come down, `policy_binds` is true and `policy_allows` gives the most sell-through policy allows. The binding constraints of an infeasible request are the targets it misses and the constraints the relaxation changes, with evidence `infeasible`. `optimizer.relaxed_request(request, relaxation)` applies a relaxation to its request. Both re-solves share the relaxation budget with the check, which takes at most half of it; `proven` is false unless the request is proven infeasible and both re-solves finished.

The `run_optimizer` tool takes the `candidate_set_id` from `generate_candidates`. It returns the status, the objective, each selected line with its numbers and why it was chosen, the plan's totals, the binding constraints, the not-selected list, the clearance shortfalls, the policy findings and the relaxation. A planning session stores the last three on the plan revision too. The `relax_constraints` tool takes the same `candidate_set_id` and returns only the status, the relaxation (`null` when the request is feasible), the binding constraints of an infeasible request, the shortfalls and the policy findings. The solver is deterministic: one worker and a fixed seed by default, and interleaved search with more workers. Each phase (the closest plan to the clearance targets, the main solve, the binding analysis and the relaxation) stops on a budget of CP-SAT *deterministic time*, which counts work done rather than seconds passed. So the same request gives the same plan, status, binding constraints and relaxation on any machine, however fast or busy it is, and recorded sessions replay (ADR 0055). The wall-clock limits are only safety nets that a healthy machine never reaches: on a machine a few times slower, a solve takes longer but ends in the same place. It is configured by:

| Setting | Default | Meaning |
|---|---|---|
| `OPTIMIZER_DETERMINISTIC_LIMIT` | `10` | Deterministic seconds per solve; with clearance targets, the closest plan takes up to half and the main solve the rest |
| `OPTIMIZER_TIME_LIMIT_SECONDS` | `60` | Wall-clock safety net per solve |
| `OPTIMIZER_WORKERS` | `1` | CP-SAT workers |
| `OPTIMIZER_SEED` | `0` | CP-SAT random seed |
| `OPTIMIZER_BINDING_DETERMINISTIC_LIMIT` | `6` | Deterministic seconds shared by the re-solves that prove which constraints bind, on top of the solve; a constraint left unsettled is `unproven`; `0` turns the analysis off |
| `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS` | `30` | Wall-clock safety net for the binding analysis |
| `OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT` | `10` | Deterministic seconds for the relaxation of an infeasible request (ADR 0044), up to half of them first spent checking whether any plan reaches every clearance target when phase 1 runs out of work (ADR 0074) |
| `OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS` | `60` | Wall-clock safety net for the relaxation |

On the seed-42 demo brief, 1,947 options are eligible with 3,796 pairwise terms. The optimal plan has 35 lines (no price match pays its way), 21 of them without clearance, worth ₹172,384 for ₹199,909 of the ₹2 lakh budget. The oracle scores it at +₹66,607 incremental profit and ₹86,654 clearance value (ADR 0037). Solving takes about 6–7 s here (CP-SAT proves the plan optimal after about 3 of its 10 deterministic seconds), within SPEC's 10 s optimiser budget: about 4.5 s is CP-SAT and about 2 s is pricing the 415,524 candidate pairs, which is vectorised (ADR 0039). Generating the candidates first takes another 7–9 s, which is timed separately and tracked in #113. Within a session the work is not repeated: when the Critic sends the plan back and the planner leaves SKUs out, `generate_candidates` reads the narrowed set off the set it generated first, and the pairwise terms already priced are reused (ADR 0077). A `model`-marker test asserts that `solve` stays under 10 s on the fitted seed-42 world. With a 50% clearance target on SKU0029, a ₹90,000 North cap and a 2% KVI tolerance, the plan has 37 lines worth ₹170,982, meets the target in both regions and solves in about 8 s; a second `model` test checks that and that the plan keeps every constraint (ADR 0040).

## Mechanism comparison

`promopilot.mechanisms.compare(sku_id, region, context, *, chosen=None)` compares the mechanisms for one SKU in one region (SPEC F-02, ADR 0041). The `ComparisonContext` is a generated candidate set, the relations model and the products. For each mechanism it picks the option with the highest value (incremental profit − cannibalisation + halo + clearance value, the optimiser's per-option objective) over every depth, duration, start week and target segment the candidate set kept. Each outcome carries the option, its effective price from `promopilot.economics` (BOGO 50% off, a FIXED_PRICE charm price ending in 9, a BUNDLE at the depth off each SKU's own base price, which is the pair's discount split pro-rata), and its expected units, revenue, gross profit, margin, promo cost, incremental profit, cannibalisation, halo, clearance value and value. A BUNDLE names its anchor, its partner and the pair's basket lift. It is compared only when the SKU has a detected complement. Mechanisms are ranked by value, highest first. A mechanism whose every option broke a per-line rule is listed last, with the rules (for example BOGO `below_cost` on a SKU that is not overstocked). `chosen`, a plan line, stands for its own mechanism instead of that mechanism's best option. The numbers are the demand model's expected values; simulator bands can join them after #39.

The `compare_mechanisms` tool takes a planning request, a SKU id and a region in the request's scope. It generates that SKU and region's options, as `generate_candidates` would, and returns the comparison with the models' versions and the as-of week. It needs no candidate set. The planning session compares every plan line on the options it already generated, and stores the comparison on the line (`mechanism_comparison`).

`promopilot.simulator.simulate(plan, inputs, *, n_runs, seed, competitor_reaction=None)` runs a promo plan through Monte Carlo (SPEC §9.5, ADR 0042). Each run draws every promo response term of every SKU from N(estimate, std error), once per SKU and run. It then draws units per store × segment × promo week from a negative binomial with the SKU's fitted dispersion, around `DemandModel.response_rows`' means. Each line is simulated on its own SKUs, as `predict` predicts it. Within a run, a SKU sells at most its pooled available stock in the region, the oracle's stock basis (ADR 0004, ADR 0011), and money follows the units sold.

The result, `PlanSimulation`, has P10/P50/P90 for each plan line and for the plan total: units, revenue, gross profit, margin, sell-through and promo spend. It also has each line's stock-out probability (demand reached its available stock) and each region's (at least one of its lines ran out). The same seed gives identical results. The `simulate_plan` tool takes 1 to 200 plan lines and an optional `n_runs` (100–5,000). Its seed, default run count and as-of week are bound, not set by the LLM. `POST /api/plans/{id}/simulate` re-simulates a session's stored plan revision the same way, with the same bounds and seed (ADR 0043).

The optional competitor reaction stress-tests a plan against a price war (F-09 AC2, ADR 0045). It is `{"match_probability": p}` with 0 ≤ p ≤ 1. In each run, each plan line draws on its own whether the competitor matches its discount, with probability p. A matched competitor cuts its price by the share our customers get off the base price (BOGO counts as 50%, FIXED_PRICE as its charm price, and a BUNDLE's partner at its own discount). That puts the competitor price index back where it was before the promotion, so the line loses the demand its competitor term (γ) gained from the discount. Undercut-sensitive SKUs, those with a positive γ, sell fewer units, and SKUs with no competitor sensitivity are unchanged. The reaction is drawn from a second generator of the same seed. Omitting it, or p = 0, therefore gives exactly the results without it, and p = 0 and p = 1 share every other draw. The planning session's own simulation never uses it. The `simulate_plan` tool and `POST /api/plans/{id}/simulate` take it as an optional `competitor_reaction`, and `PlanSimulation.competitor_reaction` records it. On the seed-42 demo plan at 1,000 runs, p = 1 moves plan P50 units from 12,866 to 11,659 and P50 gross profit from ₹463,112 to ₹441,811.

| Variable | Default | Meaning |
|---|---|---|
| `SIMULATION_RUNS` | `1000` | Runs per simulation of a plan revision, and the default of `simulate_plan` and of re-simulation (100–5,000) |
| `SIMULATION_SEED` | `0` | Seed of every simulation, so the same plan always simulates the same way |

On the seed-42 demo plan (35 lines), 1,000 runs take about 0.8 s. Units P10–P90 are 12,478–13,269 (expected 12,852), and gross profit is ₹4.45–4.81 lakh. A 100-line plan takes about 1.3 s, and a `model`-marker test asserts that it stays under 10 s.

## LLM providers

Agents reach an LLM only through `promopilot.llm` (ADR 0001, ADR 0019, ADR 0027). `LLM_PROVIDER` picks the provider:

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` (`.env`) | `replay` | `replay` answers from recorded cassettes and needs no key. `openai` or `anthropic` calls that provider live. `auto` is `openai` when its key is set, else `anthropic` when its key is set, else `replay`, and a keyed provider's model defaults to the recorded one (ADR 0073) |
| `STACK_LLM_PROVIDER` (`.env`, Docker only) | `replay` | The Docker api's `LLM_PROVIDER`. `make demo` sets `auto` |
| `LLM_CASSETTE_DIR` (`.env`) | `cassettes` | One JSON file per request hash, relative to `backend/` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` (`.env`) | empty | Needed only for `openai` and `make record-cassettes`. The model must accept `temperature=0`: use `gpt-4.1-mini` (the `gpt-5` reasoning models reject it). Keep the key in `.env`, never commit it |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (`.env`) | empty | Needed only for `anthropic`, or to make Anthropic the fallback when OpenAI is primary. Use `claude-sonnet-5` |
| `LLM_PRICES`, `USD_INR_RATE` (`.env`) | built in | Per-model prices in US dollars per million tokens (JSON), and the rupee rate for per-session cost. The defaults cover `gpt-4.1-mini` and `claude-sonnet-5` |

A live provider retries timeouts, rate limits and server errors up to 3 attempts (waiting 1 s, then 2 s). An attempt with no answer after `LLM_TIMEOUT_SECONDS` (default 60) is cancelled and counts as a timeout (ADR 0071). If it still fails and the other live provider has a key and model, that provider answers instead. Otherwise the API logs `llm_no_fallback` at startup. Every call's tokens are counted per planning session, and the cost is priced from `LLM_PRICES` when the call is made: each call is a `token_usage` trace event, and the session's `usage` is their sum (ADR 0047).

In replay mode, a request with no recorded cassette fails with `CassetteMissError` naming its hash. This usually means a prompt or schema changed and the cassettes need re-recording. Replay never falls back to another provider. A tool-calling request's hash covers the tools and every call the model made (names, arguments, ids) but not the tools' results, so a recorded planner round replays after a retrain or on another machine (ADR 0049). In a planning session the planner and the Context agent treat a miss as the LLM being unavailable: the planner logs `planner_cassette_miss` and plans with the default sequence, and the Context agent reads the brief by rules (below), so a session still gets a plan. When the api replays, each session's `demo_recording` says whether its brief, answers and amendments so far are a recorded script's (`recorded`) or not (`not_in_demo_recordings`), and the UI explains the latter as the demo's limits (ADR 0073). `make record-cassettes`, `make check-cassettes` and the committed-cassette test still fail on a miss (ADR 0053, ADR 0054). Cassettes store only the request content, the parsed response and the tokens it was billed for, never headers or keys. Tests use `FakeProvider` or `ReplayProvider` and never call a real LLM. The live smoke checks in `backend/tests/live` are marked `live` and excluded by default. Run them deliberately with keys exported: `uv run pytest -m live tests/live`.

### Recording cassettes

The committed cassettes in `backend/cassettes/` are the recording of every session script in `backend/cassettes/sessions.json`, played through the full agent graph (ADR 0054):

- `e2e`: the Playwright brief, planned;
- `demo`: the SPEC §3.2 brief, planned, amended ("Budget cut to ₹6 lakh", then "Drop West"), its relaxation accepted and approved. Its first three revisions are infeasible (the 60% namkeen clearance target is out of reach), so the script accepts revision 3's relaxation, which lowers that target to what the closest plan reaches; the fourth revision is feasible and is approved (ADR 0070);
- `clarify`: a brief with no budget, whose question is answered "₹2 lakh".
- `regional`: a Christmas brief across all regions with a South budget cap and a KVI price tolerance, planned (ADR 0058).

The home page's four example briefs are these four scripts, word for word; `frontend/tests/unit/example-briefs.test.ts` fails if one drifts from its recording.

A script is `{name, brief, steps}`, and each step is one of `{"answers": {question_id: text}}`, `{"amend": text}`, `{"accept_relaxation": true}` or `{"approve": true}`. The recorder follows the API's rules: accepting sends the latest revision's relaxation as an amendment in its own words, exactly as `POST /amend {accept_relaxation: true}` does, and approving an infeasible revision fails the recording, as `POST /approve` answers 409 (ADR 0070). `backend/cassettes/manifest.json` lists each session's script, route, cassettes in call order, plan revisions and amendment texts, and the planning settings it was recorded with.

Three checks keep them honest:

- A unit test checks the manifest against the scripts, checks that no recorded planning round runs the planner to the Critic's cap (ADR 0059), and replays every Context reading over the default world.
- An architecture test runs numeric grounding over every recorded Explainer and Critic answer (SPEC §13.4).
- CI's images job replays every whole session on the composed stack.

To re-record after changing a prompt, a schema, a script, the default world or a planning setting, run from the repository root:

```bash
make data               # the world the cassettes are recorded against
make train              # the models the planner agent's tools plan with
make record-cassettes   # needs OPENAI_API_KEY and OPENAI_MODEL=gpt-4.1-mini in .env
make check-cassettes    # replays every session from the cassettes alone, with no key
make up                 # rebuild the api image with the new cassettes
```

`make record-cassettes` plays each script on OpenAI against the loaded data and the trained models, and records every LLM request: the Context readings, the planner agent's steps in every attempt, the Critic's feedback and the Explainer's answers. It changes nothing, names the session and exits non-zero if any session:

- falls back (the Context agent reading by rules, the planner degrading, the Explainer using its template);
- asks a question its script does not answer;
- approves an infeasible revision, or accepts a relaxation its revision does not have;
- records an answer citing a number its tool data does not show.

A request asked again, in the same session or another, is answered from the cassette of its first answer, so every session replays as recorded. A full run removes every cassette no session lists, so commit the whole directory. `make record-cassettes ONLY=demo` re-records one session and keeps the others. It answers every request the named session recorded before from its cassette, so a script that gains a step asks the live model only for the new round, and the earlier rounds replay byte for byte; to ask a request afresh, delete its cassette first (ADR 0070). It prints each session's route and the live cost (a few tenths of a dollar for all four).

## API

The full reference, generated from the OpenAPI contract, is **[docs/api.md](docs/api.md)** (see the end of this section). The table below is a summary.

| Method | Path | Response |
|---|---|---|
| POST | `/api/sessions` | Start a planning session from `{"brief": "..."}` (1–2000 characters, not blank; otherwise `422`). Returns `202 {"session_id"}` at once; the session's agent graph runs in the background until it waits for a clarification or approval (ADR 0046, ADR 0048). `503` if the graph's checkpoints could not be opened |
| GET | `/api/sessions/{id}` | `{session_id, status, brief, planning_request, plan_revision, error, decisions, usage, assumptions, questions, clarifications, amendments}`; `404` if unknown. `status` is `planning`, then `awaiting_clarification` with open `questions`, or `awaiting_approval` with plan revision 1, or `failed` with an `error` saying why; then `approved` or `rejected`, and back to `planning` after an amendment. `decisions` lists every approval and rejection, oldest first (ADR 0046). `assumptions` lists how the Context agent read the brief, each `{field, value, source: brief \| data \| default, confidence, flagged, note, fallback}` (`fallback` when the brief was read by rules, ADR 0053), and `clarifications` every question answered so far (ADR 0048). `amendments` lists every amendment, oldest first, each `{text, amends_revision, relaxation, amended_at}` (ADR 0052). The revision has `solver_status`, `objective`, `binding_constraints`, `not_selected`, and `why_chosen` and `mechanism_comparison` on each line (ADR 0038, ADR 0041), `clearance_shortfalls`, `policy_findings` and, for an infeasible request, `relaxation` (ADR 0040, ADR 0044), plus its `simulation`: P10/P50/P90 per line and in total, and stock-out probabilities per line and region (ADR 0042), the `open_issues` the Critic left on it: violations of hard constraints (`kind` `violation`) and risk findings (`kind` `risk`: `OVER_CONCENTRATION`, `HEAVY_CANNIBALISATION` or `STOCKOUT_RISK`, with the `feedback` the planner was given) (ADR 0046, ADR 0051), and its `explanation`: `{summary, rationales, source, fallback_reason}`, one rationale per line, `source` `llm` or `template`, and `fallback_reason` `ungrounded`, `invalid_answer` or `llm_unavailable` when the template stood in (ADR 0050), plus `changes`, what changed from the previous revision and why, on an amended revision. An amended revision also has its `diff` from the previous one: `{from_revision, added, removed, changed, unchanged, objective_before, objective_after, objective_delta, promo_cost_before, promo_cost_after, promo_cost_delta, request_changes}`, lines matched by SKU and region, `changed` when the mechanism, depth, duration, start week, segment or bundle partner differs (ADR 0052). `usage` is `{calls, input_tokens, output_tokens, cost_usd, cost_inr, unpriced_models}`, the sums of the session's token-usage trace events (ADR 0047) |
| GET | `/api/sessions/{id}/events` | The session's trace as Server-Sent Events (ADR 0047): each event's `data` is `{id, session_id, at, node, payload}`, with `payload.kind` one of `node_started`, `node_finished`, `tool_called`, `decision`, `clarification`, `finding`, `token_usage`, and its SSE `id` is its number in the session (1, 2, ...). Send `Last-Event-ID` to get only the events after it. The stream stays open while the session plans or waits (a `: ping` comment every 15 s), and once it is `approved` or `failed` it sends `event: end` with `{session_id, status}` and closes. `404` if unknown |
| POST | `/api/sessions/{id}/clarify` | Answer the open questions with `{"answers": {question_id: text}}`: every open question's id, and no other, at most 20 answers with ids of at most 64 characters, each answer 1–2000 characters and not blank (otherwise `422`). Returns `202` with the session back in `planning` and the answers in `clarifications`; the agent graph resumes from its checkpoint in the background, reads the brief again with the answers, and plans or asks again. `409` unless the session is `awaiting_clarification`, `404` if unknown (ADR 0048) |
| POST | `/api/sessions/{id}/approve` | Approve plan revision `{"revision_number"}`, which makes it final: the status becomes `approved` and the decision joins `decisions`. Resumes the agent graph from its checkpoint, so it works after an API restart. `409` unless the session is `awaiting_approval` and the revision is its latest, or if the revision is `INFEASIBLE` (amend it first); `404` if unknown (ADR 0046) |
| POST | `/api/sessions/{id}/reject` | Reject plan revision `{"revision_number", "reason"}` (reason 1–2000 characters, not blank). The status becomes `rejected` and the session stays open for an amendment (ADR 0052). Same `409`/`404` rules as approve, except that an infeasible revision can be rejected (ADR 0046) |
| POST | `/api/sessions/{id}/amend` | Amend the planning request with `{"text"}` (1–2000 characters, not blank), or accept the latest revision's relaxation with `{"accept_relaxation": true}` (exactly one of the two; otherwise `422`). Returns `202` with the session back in `planning` and the amendment in `amendments`; the agent graph resumes from its checkpoint in the background, the Context agent reads the brief again with every amendment, and a new plan revision is planned with its `diff` and `explanation.changes`. `409` unless the session is `awaiting_approval` or `rejected`, or when accepting a relaxation the revision does not have; `404` if unknown (ADR 0052) |
| POST | `/api/plans/{id}/simulate` | Re-simulate the latest plan revision of session `{id}` from `{"n_runs": 100–5000, "competitor_reaction": {"match_probability": 0–1}}` (both optional; `n_runs` defaults to `SIMULATION_RUNS`, and an omitted or `null` `competitor_reaction` means the competitor never reacts, ADR 0045). Returns `{session_id, revision_number, demand_model, as_of_week, simulation}` and stores the new simulation on the revision in place of the old one, so `GET /api/sessions/{id}` shows it. The latest demand model and `SIMULATION_SEED` are used, and units are capped at the stock of the planning request's as-of week (ADR 0043). The stored simulation records its `competitor_reaction`. `404` for an unknown session or one without a plan revision, `422` for out-of-range `n_runs` or an invalid `competitor_reaction`, `503` with no trained demand model or no inventory snapshot, `409` if the session is approved (its plan is final, ADR 0046) or the latest model cannot simulate the stored plan, `504` if it takes longer than `TOOL_TIMEOUT_SECONDS` (nothing is stored, ADR 0071) |
| GET | `/api/models` | `{"models": [{model_id, kind, version, trained_at, as_of_week, metrics, live}]}`, newest first. `live` marks the model this API process is serving (ADR 0026) |
| POST | `/api/models/retrain` | Retrain the demand and relations models as `make train` does by default (the as-of week after the history, seed 42). The request stays open while it fits (60 to 110 seconds on the default world), then returns `201` with the new demand entry, which is now the latest and live, as is the new relations version. `409` if a retrain is already running or no data is loaded |
| GET | `/api/catalog/products` | `{"products": [{sku_id, name, brand, category, subcategory, pack_size, base_price, unit_cost, is_kvi}]}` in SKU order (ADR 0034). Optional filters `category` and `kvi_only`. `422` for an unknown category |
| GET | `/api/catalog/regions` | `{"regions": [{region, stores: [{store_id, city, segment_mix}]}]}` |
| GET | `/api/inventory` | Stock per SKU × region pooled over the region's stores, as `get_inventory_status` computes it, with name, category and overstock flag (ADR 0032, ADR 0034). Optional filters `region`, `category`, `overstocked_only` and `as_of_week` (default: the week after the loaded history). `409` if no data is loaded for the week, `422` for an unknown category or a region without stores |
| GET | `/api/competitors/gaps` | Competitor price index, gap and KVI undercut per SKU × region, widest gap first (ADR 0031). Optional filters `region`, `category`, `kvi_only` and `as_of_week` (default: the week after the loaded history). `409` if no data is loaded, `422` for an unknown category |
| GET | `/api/relations/{sku_id}` | `{model: {model_id, version, as_of_week}, sku_id, substitutes: [{sku_id, theta, std_error, q_value}], complements: [{sku_id, lift, support, theta, std_error}]}`; θ is null where not estimable. `404` for an unknown SKU, `503` when no relations model fitted on the live demand model is registered (ADR 0033) |
| GET | `/api/evals/latest` | The latest eval report, the `latest.json` that `make eval` writes into `EVAL_REPORT_DIR` (default `backend/evals/reports/`), as it was written: `{generated_at, provider, world_seed, runs_per_scenario, planning_settings, metrics, scenarios}` (see [Evals](#evals)). It is read on every request, so a new run shows at once. `404` before any run, and `404` with its own detail for a report this version cannot read, such as one written before the report changed shape; run `make eval` again. The Docker stack mounts no report folder, so it answers `404` (ADR 0069) |
| GET | `/health`, `/api/health` | Always `200` while the process runs. `/health` is for the container healthcheck; the web app uses `/api/health` through its proxy. `{"status": "ok" \| "degraded", "version", "checks": {"database": "ok" \| "error", "model_registry": "ok" \| "missing"}}`. `status` is `degraded` if the database is unreachable or no demand model is loaded |

The Context agent reads the brief into a planning request with its assumptions (ADR 0048). Its LLM lifts the brief's own phrases and stated numbers: scope, a promo window from the weeks after the as-of week or a holiday, the marketing budget in rupees, the minimum margin, clearance targets, regional budget caps, the KVI tolerance and the promoted-SKU cap (ADR 0040). Deterministic code resolves each phrase against the catalogue and calendar (ADR 0032); its match score is the assumption's confidence. Unstated optional fields take company policy's value, and data lists the overstocked SKUs and undercut KVIs in scope. A brief value that would loosen company policy is kept in the request, planned at the policy value and flagged. A revenue or volume ask gets a flagged assumption that the plan maximises profit (ADR 0005). If the marketing budget, regions, categories or promo window is missing or read below 0.7 confidence, or a clearance has no figure or unclear SKUs, the session asks instead: it becomes `awaiting_clarification` with specific questions, and `POST /clarify` resumes it. If the LLM is unavailable after its retries and fallback provider, or replay has no cassette, the Context agent reads the brief by strict rules instead (ADR 0053): the regions, categories, product names and holidays it names exactly; rupees only with ₹, Rs, INR or a lakh or crore word ("₹2 lakh", "₹90k"), placed by the words around them (a budget, or a cap written against one region, "₹90k for North"); percentages by their cue (margin, clearance, KVI tolerance); and the window from stated week ids or the one holiday named. Each value read is an assumption at confidence 0.7 marked `fallback`, and anything the rules cannot read is asked. Answers and amendments are read by the same rules ("drop West", "budget cut to ₹6 lakh"). The trace shows a `context_fallback` decision. The optimising planner then generates every promo option on the latest demand model and the live relations model, and the optimiser selects plan revision 1 with its status, binding constraints, not-selected list and a "why chosen" per line (ADR 0038). Each line also carries a comparison of the mechanisms for its SKU and region (ADR 0041). The revision is then simulated with `SIMULATION_RUNS` runs and `SIMULATION_SEED`, and the simulation is stored with it (ADR 0042). With no trained model the session fails and says to run `make train`. On the seed-42 demo brief planning takes about 25 s: about 9 s generating the options (#113), about 6 s solving, 8 s proving binding constraints and under 1 s simulating. The as-of week is the first week after the loaded sales history.

These steps run as nodes of the session's agent graph (ADR 0046): Context → Planner → Critic → Explainer → Approval, with Context → Clarify → Context when it asks (ADR 0048). The Planner is an LLM agent (ADR 0049). It is offered all 11 tools and decides which analyses to run, such as competitor gaps, mechanism comparisons, relations or inventory. It plans by calling `generate_candidates` with the planning request and `run_optimizer` on the candidate set it returns. The plan is its last successful `run_optimizer` result, built into the plan revision in process exactly as above. The planner may add or tighten regional budget caps, the KVI price tolerance and the promoted-SKU cap, but never change the brief's constraints: such a call comes back to it as an `invalid_input` error. Only `compare_mechanisms`, an analysis whose result cannot change the plan, may take the scope narrowed to the SKU and region it compares; to plan fewer SKUs, the planner leaves them out with `exclude_sku_ids` (ADR 0059). A tool that raises is retried 3 times (waiting 0.5 s, then 1 s) and then reaches the planner as a `tool_failed` error, never a crash. The planner has at most 8 LLM steps and 16 tool calls. If the LLM is unavailable after its retries and fallback provider (a mid-round failure restarts the conversation once), replay has no cassette, or no optimiser plan is reached, the default sequence plans instead, and the plan's first **planner note** says so. After the plan is chosen, the planner checks the scope's KVIs with `get_competitor_gaps`, and a planner note states each undercut and the response, e.g. "Competitor is 5.1% cheaper on SKU0002 (…) in North (₹94.90 vs ₹100.00). Matching on 1 SKU: the plan prices it at or below the competitor." Every Explainer summary, the LLM's or the template's, carries the planner notes verbatim (ADR 0050). The Critic checks each plan with `validate_plan` and reviews its risks with `review_risks` (below). A finding about one SKU points the planner at its only lever for it, leaving the SKU out with `exclude_sku_ids`: it cannot choose one SKU's mechanism or depth (ADR 0059). The LLM only rewords each risk finding's feedback for the planner, and its wording is kept only if every number in it is one the finding shows; otherwise the template feedback stands (ADR 0051). When the planner agent planned the plan, the Critic sends its violations and risk findings back to it as a message opening a fresh planner conversation, at most 3 times (so at most 4 attempts, each with the planner's own step and tool-call limits). A clean plan, an infeasible one (only an amended brief can apply its relaxation) or one the default sequence planned (it would plan the same revision again) goes straight on. So does an attempt whose findings repeat the previous attempt's exactly (the same kind, code, SKU, region, category and message, in any order; the LLM's wording is left out): the next attempt would open with the same findings and plan the same again (`findings_repeated`, ADR 0059). The best attempt (fewest violations, then fewest risk findings, then the highest objective, the later on a tie) becomes the plan revision, with its findings as open issues; earlier attempts are drafts kept only in the graph's checkpoint. The Explainer has the LLM write a summary and a rationale per plan line from the tool outputs, with every amount shown to it as it may be cited (money in lakh or crore from ₹1 lakh up). `check_numeric_grounding` checks every number; an answer that fails, or misses a plan line, is regenerated once, and a second failure or an LLM error falls back to a template written from the revision's own numbers. An infeasible or policy-bound summary always opens with the binding constraints and the relaxation. The explanation is stored on the revision with who wrote it (`llm` or `template`) and why the template was used (ADR 0050). Until full-graph cassettes are recorded (#51), the replayed Docker stack shows template explanations. The graph then pauses at the Approval interrupt, and the session becomes `awaiting_approval`. An amendment (`POST /amend`, while awaiting approval or rejected) resumes it into the Context agent, which reads the brief again with every amendment, oldest first, and a new planning round: the next plan revision is numbered after the last and stores its diff from it (lines added, removed and changed by SKU and region, the objective and promo-cost deltas, and the planning-request changes), computed by `guardrails.diff_revisions`. The Explainer says what changed and why from that diff, grounded like the rest; the amendment's own words are never in its view. Accepting a relaxation is an amendment whose text states each change exactly (ADR 0052). Its state is checkpointed in Postgres by LangGraph's checkpointer (psycopg 3, tables created at API startup), so an answer, approve or reject after an API restart resumes it from the checkpoint. A session still `planning` when the API restarts fails, as before. On Windows, run the API with a selector event loop: `make dev`'s `--reload` does.

Every step of the graph is a trace event, stored in Postgres in order (ADR 0047): each node's start and end (`completed`, `interrupted` at an interrupt, or `failed` with its error), each billed LLM call with its tokens and cost, the Critic's findings and route, and each approval or rejection. `GET /api/sessions/{id}/events` streams them live, polling every `TRACE_POLL_INTERVAL_S` seconds (default 0.5), and the web proxy passes the stream through unbuffered. The API logs JSON lines (`LOG_FORMAT=json`, or `console` for readable text); every line logged while a session plans carries its `session_id` and the graph `node`.

`promopilot.guardrails` holds the E8 checks that need no LLM (ADR 0028):

- `validate_plan(plan, request, policy)` returns a violation for every hard constraint a plan breaks on its own plan-time numbers (ADR 0012). The checks are budget, minimum margin, margin floor, stock, maximum discount, below cost, promo window, maximum promoted SKUs per category per region, one plan line per SKU per region, and no two strong substitutes promoted together (`STRONG_SUBSTITUTES`, on the relations model's pairs that `PlanFacts.substitutes` carries, ADR 0075).
- `check_numeric_grounding(text, tool_outputs)` lists every number in a text that no tool output supports, at the precision the text shows. It reads ₹, lakh, crore and percentages.
- `format_rupees`, `format_percent` and `format_units` show numbers the way explanations cite them (₹18,250, ₹1.72 lakh, ₹1.25 crore, 22.4%, 1,23,456), rounded so that grounding always accepts them (ADR 0050).

- `review_risks(revision, facts, request, thresholds)` returns the plan's risk findings, each with a message and template feedback naming the planner's levers (ADR 0051): a plan line above `CRITIC_LINE_SPEND_SHARE` of the promo spend (checked only when the plan has enough lines for none to need that much), a category or region above `CRITIC_GROUP_SPEND_SHARE` when the scope has several, a line whose cannibalisation is at least `CRITIC_CANNIBALISATION_SHARE` of its incremental profit, and a line whose simulated stock-out probability is at least `CRITIC_STOCKOUT_PROBABILITY`.

| Variable | Default | Meaning |
|---|---|---|
| `CRITIC_LINE_SPEND_SHARE` | `0.25` | A plan line above this share of the plan's promo spend is over-concentrated |
| `CRITIC_GROUP_SPEND_SHARE` | `0.8` | So is a category or region above this share, when the scope has more than one |
| `CRITIC_CANNIBALISATION_SHARE` | `0.5` | Cannibalisation at or above this share of a line's incremental profit is heavy |
| `CRITIC_STOCKOUT_PROBABILITY` | `0.2` | A line that runs out of stock in at least this share of simulated runs is a stock-out risk |

The Critic and the Explainer call them.

### Errors, limits and timeouts

Every error answers one schema (ADR 0071): `{"detail", "code", "reference_id", "errors"}`. `detail` is the sentence to show. `code` follows the status: `not_found` (404), `conflict` (409), `payload_too_large` (413), `validation_failed` (422), `rate_limited` (429), `internal_error` (500), `api_unreachable` (the web proxy's 502), `unavailable` (503) and `timeout` (504); any other 4xx is `bad_request`. `reference_id` is the request's id, which every response, successful or not, also carries as `X-Request-ID`. A 422's `detail` is its first problem as a sentence, such as `brief: String should have at most 2000 characters`, and `errors` lists every problem as `{loc, message}`, never echoing the input; `errors` is `null` otherwise. An unexpected error is a `500` whose body names only the reference id, never the exception or a traceback; the API logs it as `api.unexpected_error` with the id. The web app shows every failure inline with its message and a **Reference** line to quote.

Briefs, amendments, answers and rejection reasons are 1–2000 characters, a clarify takes at most 20 answers, and a category or SKU id in a query or path at most 64 characters. The OpenAPI contract states them, and the web app's forms stop at the same limits (a test checks them against `docs/openapi.json`). A request body over `MAX_REQUEST_BODY_BYTES` is `413` before the API reads it.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_TIMEOUT_SECONDS` | `60` | An LLM attempt with no answer by then is retried as a timeout, then the fallback provider answers, then the agents degrade as when the LLM is down |
| `TOOL_TIMEOUT_SECONDS` | `120` | A tool call still running by then is a `timeout` tool error the planner reads; a re-simulation is `504`. Keep it above the optimiser's wall-clock nets |
| `SESSION_TIMEOUT_SECONDS` | `900` | A session's background graph run (the start, or the resume after clarify or amend) that has not paused by then fails the session with "Planning took longer than 900 s and was stopped." after a `session_timed_out` decision in its trace |
| `MAX_REQUEST_BODY_BYTES` | `262144` | The largest request body the API reads (at least 1024) |
| `RATE_LIMIT_PLANNING_PER_MINUTE` | `20` | Requests a minute each client may make to create, amend or clarify a session, together, in bursts of up to the limit; `0` turns the limit off |
| `RATE_LIMIT_SIMULATIONS_PER_MINUTE` | `30` | Re-simulations (`POST /api/plans/{id}/simulate`) a minute each client may make, in bursts of up to the limit; `0` turns the limit off |

A client over a rate limit gets `429 rate_limited` with the error schema, a sentence such as "Too many planning requests from this client: at most 20 a minute. Try again in 3 s." and a `Retry-After` header in whole seconds (ADR 0079). Each limit is a token bucket per client, kept in the API process: every attempt counts, an invalid one included, and a refused one takes nothing. Reading sessions, their events, approving and rejecting are never limited. The client is the connection's address as uvicorn reports it, so behind the web app's proxy every browser shares one budget; uvicorn's `FORWARDED_ALLOW_IPS` decides which proxy may name the real client. With several uvicorn workers, each keeps its own buckets. `docker-compose.yml` does not pass these settings through, so `make up` and `make demo` run with the defaults.

A brief, an amendment, an answer or a reason is data, never instructions (ADR 0079). The agents' prompts carry it only as a quoted JSON string. Whatever the LLM makes of it, the tools check every call on their own: an unknown tool is `unknown_tool`, and arguments that break a tool's input schema are `invalid_input` before the tool runs, a key the schema does not declare included, at any depth. A brief value that would loosen company policy is flagged and the policy value applies, the planner may not loosen the brief's constraints, and `estimate_demand` and `simulate_plan` refuse a line deeper than the company-policy maximum discount. The integration tests in `backend/tests/integration/test_adversarial_briefs_api.py` play prompt-injection briefs through the API against an LLM scripted to obey them.

The API reference is [docs/api.md](docs/api.md): every endpoint, its parameters, request and response bodies, error statuses and headers, and every schema with its fields and limits. It is generated from the machine-readable contract, [docs/openapi.json](docs/openapi.json), by `make api-types` (or `make api-docs` from the committed contract alone), so do not edit it by hand. CI's contract job fails when the committed page, the contract or the frontend types drift from the code, and `make test` fails when the page drifts from the committed contract (ADR 0082). Interactive docs are at http://localhost:8000/docs while the API runs.

## Evals

`make eval` measures the reliability claim (SPEC §12, ADR 0056). It plays every scenario in [`backend/evals/scenarios/`](backend/evals/scenarios) as a planning session through the full agent graph, in process, and scores each session's final plan revision. `ONLY="a b"` runs the named scenarios, `RUNS=n` runs each n times, and `SEED=n` picks the world.

A scenario is one YAML file, named after it:

```yaml
name: demo-budget-cut-drop-west
group: mid_plan_amendments     # one of the nine SPEC §12.1 groups
brief: >-
  Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. …
as_of_week: 104                # the week it treats as today (ADR 0008)
seed: 0                        # its sessions' optimiser and simulation seed
clarifications:                # answers by question id, given only if that question is asked
  marketing_budget: "₹2 lakh"
amendments:                    # made in order, each once a plan waits for approval
  - "Budget cut to ₹6 lakh"
  - "Drop West"
  - accept_relaxation: true    # accept the waiting revision's relaxation, as the API does
labels:                        # the planning-request fields it states, for extraction accuracy
  regions: [North]
  marketing_budget: 600000
expect:                        # properties of the outcome, never an exact plan
  - asks_clarification: marketing_budget
  - declares_infeasible: false
  - excludes_region: West       # the final revision, after every amendment
  - meets_clearance: SKU0002
  - relaxation_touches: clearance_target   # a ConstraintKind the relaxation changes
  - flags_assumption: min_margin           # the final reading flags this field
  - diff_changes: scope.regions            # the final revision's diff changes this field
  - kvi_response_present: true             # the undercut-KVI response is in notes and summary
  - no_strong_substitutes_together: true   # no two strong true substitutes promoted together
```

A `vague_or_conflicting` scenario must name at least one field with `asks_clarification` or `flags_assumption` (ADR 0062).

An amendment is a text, or `accept_relaxation: true`. Accepting sends the waiting revision's relaxation as an amendment in its own words, exactly as `POST /amend {accept_relaxation: true}` does, and counts in the run's amendments. A revision with no relaxation to accept fails the run, as the API answers 409 (ADR 0076). The labels stay what the scenario states: an accepted relaxation's values replace the labelled values it changes before extraction is scored, and `meets_clearance` checks the target the final request holds, the relaxed one after an accept. The runner never approves; `declares_infeasible: false` says the final revision could be approved. The demo scenario amends twice, accepts revision 3's relaxation and expects a feasible revision 4 whose diff changes `clearance_targets`.

A labelled promo window must start after the as-of week. `no_strong_substitutes_together` fails when the final plan promotes two strong substitutes in scope together, or when the scope has none to test. Two SKUs are strong substitutes when the ground truth makes them a substitute pair and the larger of their true cross-price effects θ is at least 0.5. They are promoted together when they share a region, a promo week and a target segment, and a BUNDLE's partner counts (ADR 0065).

The suite has SPEC §12.1's 32 scenarios, one flat file each (ADR 0065):

| Group | Count | As-of weeks |
|---|---|---|
| Standard festive plans | 6 | 50, 62, 104 |
| Tight budget | 4 | 50, 62, 82, 104 |
| Overstock clearance | 4 | 50, 62, 82, 104 |
| Competitor price war | 4 | 50, 62, 82, 104 |
| Regional holidays | 3 | 50 (Durga Puja), 62 (Pongal, Lohri) |
| Heavy cannibalisation | 3 | 62, 82, 104 |
| Vague or conflicting briefs | 3 | 62, 82, 104 |
| Infeasible constraints | 2 | 50, 104 |
| Mid-plan amendments | 3 | 62, 82, 104 |

Week 50 reaches Durga Puja and Diwali 2025, week 62 Christmas 2025 and Pongal/Lohri 2026, week 82 an off-season window, and week 104 Durga Puja, Diwali and Christmas 2026. Every brief outside the vague group states its weeks, regions, categories, rupees and percentages. A test checks that the Context agent's rules read each of those briefs to its labels with the LLM down. Another checks each scenario on the seed-42 world: its SKUs have stock to clear, a price war's KVIs are undercut, and a cannibalisation scope holds strong substitute pairs.

The eval builds its own world: the seed-42 dataset `make data` writes, with its hidden ground truth, and demand and relations models fitted in memory as of each scenario's week (35–60 s per week), so no sales after that week reach them. It needs no Docker, `make data` or `make train`. The LLM is whatever `LLM_PROVIDER` names; with the default `replay`, requests with no cassette fall back as the stack does: the Context agent reads by rules, the planner runs the default sequence and the Explainer uses its template, and each run lists what fell back. The three starter scenarios are the recorded sessions' briefs (`e2e`, `clarify`, `demo`), and on the seed-42 world they replay the committed cassettes whole, taking the recorded routes with nothing falling back. Replay reads the eval's own cassettes in `backend/evals/cassettes/` first, then the app's `backend/cassettes/`. A scenario with no cassettes falls back until it is recorded. Until the suite is recorded, a full run takes about 40 minutes, because the new scenarios plan by the default sequence. Once recorded, it takes about 80–130 minutes (150–250 s a session, plus four fits of 35–60 s, plus about 30 s for each distinct final request to build the baseline and best plans). `RUNS=5` takes five times that. A question the scenario does not answer ends its run with no plan, and a failed session is reported without stopping the others.

`make record-eval-cassettes` records the suite with a live key (`OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4.1-mini` in `.env`; no Docker). It asks the live model only what neither cassette folder holds, writes the answers into `backend/evals/cassettes/`, and prints the live cost. It is additive: to record afresh, empty the folder first. `make record-cassettes` cannot record eval scenarios, since it plays on the week-104 registered models and prunes what its manifest does not list. Recording all 32 is about 37 planning rounds, roughly $2–7.5 (₹190–720) at gpt-4.1-mini, and 1.5–3 hours.

The report goes to `backend/evals/reports/` (gitignored) as `<UTC timestamp>.json` and `.md`, plus `latest.json` and `latest.md`. It shows each metric against its SPEC §12.2 target, one row per run and every failure:

- **Constraint satisfaction** (target 100%): the share of final plans that keep every hard constraint on their own plan-time numbers, checked by `validate_plan` independently of the optimiser (ADR 0012). Infeasible revisions and runs without a plan are counted but not scored.
- **Oracle breach rate** (reported, no target): the share of the same plans whose true outcome, scored by the oracle on the hidden demand, spends over the budget, misses the minimum margin or sells more than the stock, with a count of each.
- **Extraction accuracy** (target ≥ 95%): correct labelled fields over labelled fields, on the final planning request. Sets match as sets, money within ₹1, fractions within 0.01 points, windows and the SKU cap exactly; a run with no request gets every labelled field wrong. A mismatch is listed but does not fail its run (ADR 0062).
- **Clarification behaviour** (target 100%): the share of `vague_or_conflicting` runs that asked about, or flagged, a field the scenario names. Runs of other scenarios that asked a question they do not expect are counted as unneeded asks, with no target.
- **Infeasibility handling** (target 100%): the share of `infeasible_constraints` runs whose final revision is `INFEASIBLE`, proposes a relaxation and names a binding constraint. A solver timeout is not a declaration.
- **Grounding** (target ≥ 98%): the share of Explainer runs the LLM answered (one per revision that waited for approval, amendments included) whose explanation passed numeric grounding. A template for an ungrounded or invalid answer fails; one because the LLM was unavailable, a cassette miss included, is counted but not scored.
- **P50 session time and cost** (reported): the median wall-clock time of the sessions that did not fail, from the brief to the session's end (without fitting the models or scoring the plan), with the median time spent waiting on the LLM (`llm_p50_s`, near 0 under replay) in its breakdown, and their median LLM cost in rupees, the sum of each session's token-usage events priced with `LLM_PRICES`. Replay reports the recorded usage again, so a cassette miss costs nothing. SPEC §6 aims for under 60 s with a live LLM and under ₹20 a session.
- **Model recovery** (ADR 0064), once per report on the models fitted as of the world's default week (104, the models `make train` registers; fitted if no scenario uses that week):
  - **Elasticity recovery** (target ≤ 20%): the median absolute % error of the estimated own-price elasticity against the true one, over every SKU × segment, with how many are within 20%.
  - **Substitute and complement precision / recall** (targets ≥ 0.8 / ≥ 0.7): the pairs the relations model keeps, as unordered pairs across the catalogue, against every true pair.
  - **Baseline WAPE** (reported, aim ≤ 25%): the demand model's own 12-week holdout WAPE at the store × SKU × segment, store × SKU and region × SKU grains (ADR 0023).
- **Plan quality** (target 90%): the share of scenarios whose every scored plan earns more, by the oracle's objective (incremental profit plus clearance value), than the **rule-based baseline**. That baseline is 20% off the top 10 sellers in scope (units over the 12 weeks before the as-of week), to All customers, in every region of the scope, over the promo window (at most its first 4 weeks), with sellers dropped from the bottom until its expected promo cost fits the budget and any regional cap (ADR 0063).
- **Regret** (target: median 10% or less): (best − ours) / best, where the **best plan** is our own option generation and optimiser run on true-parameter predictions from the ground truth, with the session's work budgets and the scenario's seed, scored by the oracle. It is signed; when the best plan earns nothing, matching it is 0 and earning less is 100%.
- **Consistency** (target 0.9): the mean Jaccard overlap of the SKUs every two runs of a scenario promote. It needs `RUNS` of at least 2 (`make eval RUNS=5`), so the default run shows it as n/a. With the replay provider a scenario's runs are identical: only a live LLM varies them.
- **Expected properties**: each scenario's `expect` list, pass or fail per run.

A second table, **Agent behaviour**, shows per run the fields read right, the questions asked, the flagged assumptions, each Explainer run's source, the session time with its LLM time, and its cost.

The harness builds the baseline and the best plan from each run's final planning request, never from the scenario file, once per scenario seed and request. The report's plan-quality table shows each scored plan against both.

Each run also lists its `cassette_misses`: the hash of every request replay held no cassette for, in any round (ADR 0069), and whether it `passed`: it ran, kept its hard constraints and had every expected property (ADR 0072). `/evals` shows the report.

### Smoke eval in CI

Five scenarios carry `smoke: true`, and CI's `eval-smoke` job replays them on every PR with no key (ADR 0069): `diwali-snacks-beverages` (week 104, standard festive), `diwali-no-budget` (104, vague: asks for the budget), `infeasible-clearance-high-margin` (50, infeasible), `amend-budget-cut-christmas-2025` (62, mid-plan amendment) and `price-war-bakery-beverages-offseason` (82, price war). They cover five of the nine groups and every as-of week, so every model history is fitted on Linux.

`make eval-smoke` runs the same thing locally: `python -m promopilot.evals --smoke --check` with `LLM_PROVIDER=replay`. `--smoke` plays only the tagged scenarios (`make eval SMOKE=1` without the check). `--check` exits 3 when a run:

- ends with no plan (failed, or still asking);
- has a final plan that breaks a hard constraint, or an expected property that does not hold;
- is a vague scenario that neither asked nor flagged, or an infeasible one not declared infeasible with a relaxation and a binding constraint;
- asked anything no cassette holds, named by its request hash.

The ratio metrics (plan quality, regret, extraction, grounding, model recovery) are in the report but never fail the check. A fallback the recording itself made replays as recorded and is not a problem. `--check` needs the replay provider. The job needs no Docker, `make data` or `make train`, takes about 22–28 minutes (four fits and six planning rounds), puts `latest.md` in the job summary and uploads `backend/evals/reports/` as the `eval-smoke-report` artifact. A cassette miss that only CI sees usually means a number formatted differently on Linux (ADR 0054 D12): take the raw number out of the request rather than recording on Linux.

## Repository layout

```
backend/    FastAPI app (src/promopilot), tests, uv project
frontend/   Next.js App Router app, Vitest unit tests, Playwright e2e
docs/adr/   Architecture decision records
docs/api.md The API reference, generated from docs/openapi.json (make api-types)
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
- [ADR 0040: Clearance targets solve in two phases; regional caps, the KVI tolerance and a tighter SKU cap are plan-level constraints; a brief only tightens policy](docs/adr/0040-clearance-targets-regional-caps-and-kvi-tolerance.md)
- [ADR 0041: Mechanisms are compared on the candidate set's expected numbers, by value, with the plan line standing for its own mechanism](docs/adr/0041-mechanism-comparison.md)
- [ADR 0042: Every plan revision is simulated: one term draw per SKU and run, negative binomial noise per store, units capped at pooled regional stock](docs/adr/0042-monte-carlo-simulation-of-plan-revisions.md)
- [ADR 0043: A stored plan is re-simulated through its session: the latest plan revision, on the latest demand model, replacing its stored simulation](docs/adr/0043-re-simulate-the-latest-plan-revision.md)
- [ADR 0044: An infeasible request is one no plan reaches every clearance target of; its relaxation minimises the relative change to the brief's own constraints](docs/adr/0044-infeasible-requests-and-minimal-relaxation.md)
- [ADR 0045: A competitor reaction is drawn per plan line and run from its own seeded stream, and a match puts the competitor price index back where it was before the promotion](docs/adr/0045-competitor-reaction-in-simulation.md)
- [ADR 0046: Planning sessions run a checkpointed agent graph that pauses at Approval, and every approval or rejection is kept as the session's audit trail](docs/adr/0046-agent-graph-with-checkpointed-approval.md)
- [ADR 0047: Every step of the agent graph is a numbered trace event in Postgres, streamed over SSE, and a session's cost is the sum of its token-usage events](docs/adr/0047-live-trace-events-over-sse.md)
- [ADR 0048: The Context agent's LLM only lifts the brief's phrases and stated numbers; deterministic code resolves them into assumptions with a confidence, or into clarification questions answered in free text](docs/adr/0048-context-agent-assumptions-and-clarification.md)
- [ADR 0049: The Planner is an LLM agent over the tool registry whose plan is its last optimiser result, and it falls back to the default sequence when it cannot reach one](docs/adr/0049-llm-planner-agent-with-graceful-degradation.md)
- [ADR 0050: The Explainer's LLM cites amounts pre-formatted in lakh or crore, is regenerated once when ungrounded, and falls back to a stored template explanation](docs/adr/0050-grounded-explainer-with-template-fallback.md)
- [ADR 0051: The Critic finds risks deterministically, has the LLM word only the feedback, and loops a planner-agent plan back at most 3 times before the best attempt goes on](docs/adr/0051-critic-loop-with-deterministic-risk-review.md)
- [ADR 0052: An amendment resumes Approval into a Context re-read and a new planning round, whose plan revision stores a deterministic diff that the Explainer says in words](docs/adr/0052-amendments-with-revision-diffs.md)
- [ADR 0053: When the LLM is down, the Context agent reads the brief by strict rules into low-confidence assumptions, and asks about anything the rules cannot read](docs/adr/0053-deterministic-context-fallback.md)
- [ADR 0054: Cassettes record scripted sessions through the full agent graph, listed in a manifest, checked for grounding offline and replayed in CI](docs/adr/0054-full-graph-session-cassettes.md)
- [ADR 0055: Each optimiser phase stops on a CP-SAT deterministic-time budget, with wall-clock limits only as safety nets, so a plan never depends on the machine](docs/adr/0055-deterministic-time-optimiser-budgets.md)
- [ADR 0056: The eval runner plays YAML scenarios through the agent graph in process, on its own seeded world, and checks each final plan on its plan-time values before scoring it with the oracle](docs/adr/0056-eval-runner-and-scenarios.md)
- [ADR 0057: The session page streams its trace with the browser's EventSource, reopens a stream it gave up on with backoff and drops repeated event ids, and shows each node run with its steps beside the session](docs/adr/0057-live-session-page-trace-timeline.md)
- [ADR 0058: The home page offers four recorded example briefs, and its optional constraint form adds sentences to the brief rather than changing the API](docs/adr/0058-home-page-example-briefs-and-constraint-form.md)
- [ADR 0059: The Critic loop converges: the planner leaves a flagged SKU out with `exclude_sku_ids`, analyses may narrow the scope, and repeated findings end the loop early](docs/adr/0059-critic-loop-converges.md)
- [ADR 0060: The plan shows in a tab per region plus a side-by-side tab; plan lines keep their uplift, segment uplift and cross effects, and a frontend map names each number's tool](docs/adr/0060-region-plan-tabs-and-sourced-numbers.md)
- [ADR 0061: The session page lists every assumption and highlights readings below 0.9 confidence, flagged values and rule readings, and asks open questions as a form whose answers resume planning at once](docs/adr/0061-assumptions-panel-and-clarification-form.md)
- [ADR 0062: Agent-behaviour metrics score each session's final request, questions, flags, infeasibility and Explainer runs, and its time and cost from its trace](docs/adr/0062-agent-behaviour-metrics.md)
- [ADR 0063: Plans are measured against a rule-based baseline and our own optimiser on true parameters, both built by the harness from each run's final request, and runs of a scenario against each other](docs/adr/0063-plan-quality-baseline-regret-consistency.md)
- [ADR 0064: Model-recovery metrics read the eval world's own fit at its default week and report elasticity error, pair detection and the holdout WAPE](docs/adr/0064-model-recovery-metrics.md)
- [ADR 0065: The scenario suite has SPEC §12.1's 32 scenarios at four as-of weeks, briefs the rules can read, a seed-42 coherence test, and its own cassettes that a record mode adds to](docs/adr/0065-scenario-suite-across-the-nine-groups.md)
- [ADR 0066: The session page reviews the latest plan revision in one card that approves after a confirm, rejects with a reason and amends; the revision's diff shows in the plan, and an audit trail lists every amendment and decision](docs/adr/0066-amend-diff-approve-and-reject.md)
- [ADR 0067: The constraint checklist reads pass or fail from the revision's open violations; the not-selected list shows the optimiser's own top five; an infeasibility panel shows the shortfalls, binding constraints and relaxation, accepted in one click](docs/adr/0067-constraint-checklist-not-selected-and-infeasibility-panel.md)
- [ADR 0068: The simulation card charts each plan line's P10–P90 band and P50 and re-simulates a plan awaiting a decision against a competitor reaction; a competitor card shows the KVI gaps in scope, the plan line promoting each, and the planner's response kept on the explanation](docs/adr/0068-simulation-band-chart-and-competitor-panel.md)
- [ADR 0069: CI replays five tagged smoke scenarios across four weeks and fails on a session with no plan, a broken check or any cassette miss; the API serves the latest report as it was written](docs/adr/0069-smoke-eval-in-ci-and-latest-report-api.md)
- [ADR 0071: Every API error answers `{detail, code, reference_id}`; inputs are capped in the request types and the body; LLM attempts, tool calls and background graph runs time out from config](docs/adr/0071-one-error-schema-input-limits-and-timeouts.md)
- [ADR 0072: The `/evals` dashboard shows the latest report as it was written: grouped metric cards with the report's own pass or fail, a sorted and clipped regret chart, and a scenario table whose "trace" is each run's detail in the report](docs/adr/0072-evals-dashboard.md)
- [ADR 0073: `make demo` prepares the data and models in an init step, replays unless `.env` holds a key, and explains a brief outside the recordings instead of failing it](docs/adr/0073-make-demo-from-a-fresh-clone.md)
- [ADR 0074: A plan that misses a clearance target is INFEASIBLE, settled by a feasibility check when the closest-plan search runs out of work; a solve that finds no plan in time returns the greedy plan](docs/adr/0074-timed-out-plans-are-validated.md)
- [ADR 0075: Strong substitutes are never promoted together: a hard, always-on company-policy rule on the relations model's estimated θ, at most one option per pair, region, week and segment](docs/adr/0075-never-promote-strong-substitutes-together.md)
- [ADR 0076: An eval scenario's amendment can accept the waiting revision's relaxation, sent as the API sends it; the labels stay as stated and the accepted values replace them when scored](docs/adr/0076-eval-scenarios-accept-a-relaxation.md)
- [ADR 0077: The performance pass reuses work within a session: one baseline forecast per region, a loop-back read off the first candidate set, each option pair priced once, and session time that ends with the session](docs/adr/0077-performance-pass-reuses-work-within-a-session.md)
- [ADR 0082: The API docs are Markdown generated from the OpenAPI contract by a small stdlib script that `make api-types` runs, and CI fails when the committed page drifts](docs/adr/0082-api-docs-generated-from-the-contract.md)

The domain glossary is [CONTEXT.md](CONTEXT.md).

## License

[MIT](LICENSE)
