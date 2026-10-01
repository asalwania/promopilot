# Running PromoPilot

How to run the demo and the development stack, the settings, the LLM providers and recorded cassettes, and a tour of the web app. The short version is in the [README](../../README.md).

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

The `/evals` page shows the recorded full eval run baked into the api image (33 scenarios, `backend/evals/published/`).

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

The **Evals** link opens `/evals`, the latest [eval report](evals.md) from `GET /api/evals/latest`:
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

`make demo` does all of this in one command (see [Try it](#try-it-make-demo)). The Docker stack needs no API key. Under `make up` Compose runs the api with `LLM_PROVIDER=replay` and the cassettes baked into its image, whatever `.env` says (ADR 0022). Under `make demo` it replays unless `.env` holds a key (ADR 0073). CI's `demo` job runs `make demo` from a clean checkout, replays every recorded session from the cassettes alone (`python -m promopilot.cassettes --check`, ADR 0054), then Playwright types the `e2e` brief from `backend/cassettes/sessions.json`, clicks **Plan it**, waits for the plan, checks the region tabs, a source tooltip, a line's details and its mechanism drawer, the West tab and the side-by-side view, checks the constraint checklist and the not-selected list, checks the competitor prices (an undercut and the planner's response) and the simulation chart, then re-simulates with a 50% competitor match probability and checks the stress-test label and the stored reaction (ADR 0068; re-simulating makes no LLM call), checks that the live trace shows the agent's node runs, tool calls and Critic decision and that the usage meter counts the replayed calls, and checks that the Explainer's recorded answer explains the plan. A second journey types the `clarify` brief, sees the budget question and the assumptions panel, answers with the recorded answer and waits for the plan (ADR 0061). A third journey plans the `demo` brief and amends it with its two recorded amendments, checking each revision's diff and that every revision is feasible, with a passing clearance check. It approves revision 3 and sees the session **Final**, with both amendments and the approval on the audit trail (ADR 0086). A fourth plans the `infeasible` brief: revision 1 cannot be approved, and shows its binding clearance targets, its relaxation, the accept button and a failing clearance check (ADR 0067). It clicks **Accept the relaxation and re-plan**, sees revision 2's diff with the clearance-target change, approves it and sees the session **Final**, with the accepted relaxation badged on the audit trail (ADR 0070, ADR 0086). Two more plan the `e2e` brief and approve it (the session becomes final) or reject it with a reason (the session stays open for an amendment) (ADR 0066); the approved one keeps its simulation chart with no **Re-simulate** (ADR 0068). Another types a brief of its own and sees the **Demo mode** badge and the **Not in the demo recordings** note, before and after **Plan it**, with no error, and `/evals` shows the baked report. The job then runs `make demo` again and checks that the init step skipped both the data and the models (ADR 0073).

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
| `make api-types` | Export OpenAPI to `docs/openapi.json`, regenerate the frontend types and the [API reference](../api.md) |
| `make api-docs` | Regenerate only the [API reference](../api.md) from the committed `docs/openapi.json` |
| `make data` | Generate the seeded synthetic dataset into `data/generated/` (Parquet) and its hidden ground truth into `data/ground_truth/`, then load the tables into Postgres (starts it if needed) |
| `make record-cassettes` | Record every scripted session's LLM calls with a live OpenAI key; `ONLY=name` re-records one session (see [Recording cassettes](#recording-cassettes)) |
| `make check-cassettes` | Replay every scripted session through the full agent graph from the cassettes alone, with no key |
| `make train` | Fit the demand model, then the relations model, on the loaded data (`make data` first) and register both (see [Demand model](planning.md#demand-model) and [Relations](planning.md#relations)) |
| `make eval` | Play the eval scenarios on their own seeded world and write the report to `backend/evals/reports/`; `ONLY="a b"`, `SMOKE=1`, `RUNS=n`, `SEED=n` (see [Evals](evals.md)). Needs no Docker, `make data` or `make train` |
| `make eval-smoke` | What CI runs: replay the five smoke scenarios with no key and fail on a session with no plan, a broken constraint or expected property, or any cassette miss (see [Smoke eval in CI](evals.md#smoke-eval-in-ci)) |
| `make record-eval-cassettes` | Play the eval scenarios with a live OpenAI key and record what no cassette holds into `backend/evals/cassettes/`; `ONLY="a b"` records some. Costs money (see [Evals](evals.md)) |
| `make demo` / `make demo-down` / `make demo-reset` | The one-command demo in Docker, with no API key: seed-42 data, trained models and the app; stop it keeping its volumes; or delete them (see [Try it](#try-it-make-demo)) |


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
- `demo`: the SPEC §3.2 brief, planned, amended ("Budget cut to ₹6 lakh", then "Drop West") and approved. Every revision reaches the 60% namkeen clearance targets, so revision 3 is approved (ADR 0086);
- `clarify`: a brief with no budget, whose question is answered "₹2 lakh";
- `regional`: a Christmas brief across all regions with a South budget cap and a KVI price tolerance, planned (ADR 0058);
- `infeasible`: 95% of the 400g namkeen stock on a ₹10k budget, which no plan reaches. Revision 1 is infeasible, so the script accepts its relaxation, which lowers the targets (and raises the budget) to what the closest plan needs; revision 2 is feasible and is approved (ADR 0070, ADR 0086).

The home page's four example briefs are the first four scripts, word for word; `frontend/tests/unit/example-briefs.test.ts` fails if one drifts from its recording.

A script is `{name, brief, steps}`, and each step is one of `{"answers": {question_id: text}}`, `{"amend": text}`, `{"accept_relaxation": true}` or `{"approve": true}`. The recorder follows the API's rules: an accept step accepts the latest revision's relaxation exactly as `POST /amend {accept_relaxation: true}` does (its text is recorded, and code applies its values, ADR 0083), and approving an infeasible revision fails the recording, as `POST /approve` answers 409 (ADR 0070). `backend/cassettes/manifest.json` lists each session's script, route, cassettes in call order, plan revisions and amendment texts, and the planning settings it was recorded with.

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

`make record-cassettes` plays each script on OpenAI against the loaded data and the trained models, and records every LLM request: the Context readings, the planner agent's steps in every attempt, the Critic's feedback and the Explainer's answers. It changes nothing, names the session and exits non-zero if any session (a refused run writes the Explainer's live requests and answers to `backend/cassettes/failed/`, git-ignored, to see what it was shown and wrote when it fell back, ADR 0090):

- falls back (the Context agent reading by rules, the planner degrading, the Explainer using its template);
- asks a question its script does not answer;
- approves an infeasible revision, or accepts a relaxation its revision does not have;
- records an answer citing a number its tool data does not show.

A request asked again, in the same session or another, is answered from the cassette of its first answer, so every session replays as recorded. A full run removes every cassette no session lists, so commit the whole directory. `make record-cassettes ONLY=demo` re-records one session and keeps the others. It answers every request the named session recorded before from its cassette, so a script that gains a step asks the live model only for the new round, and the earlier rounds replay byte for byte; to ask a request afresh, delete its cassette first (ADR 0070). It prints each session's route and the live cost (a few tenths of a dollar for all four).
