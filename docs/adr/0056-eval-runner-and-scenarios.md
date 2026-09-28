# The eval runner plays YAML scenarios through the agent graph in process, on its own seeded world, and checks each final plan on its plan-time values before scoring it with the oracle

E9 starts with #52: the harness that the reliability claim (D2) is measured with. Scenarios are
files, `run(scenarios, provider, runs_per_scenario)` plays them as planning sessions and scores
every final plan revision, and `make eval` writes the report. Its first two metrics are
constraint satisfaction and the oracle breach rate (ADR 0012). Baseline, regret and consistency
(#53), model recovery (#54) and the agent-behaviour metrics (#55) add to the same report, #56
grows the suite to 30 scenarios, and #57 adds the CI smoke eval and `GET /api/evals/latest`.

SPEC §12, #11 and #52 leave open:

- the scenario file's shape, and when answers and amendments are given;
- how a session is driven, and what world and models it plans on;
- what the seeds control;
- which plans each metric counts;
- the report, the provider and the command.

We chose these with the owner (D1–D13 on #52; every recommended option).

## Decisions

- **D1. One YAML file per scenario in `backend/evals/scenarios/`, named after it** (SPEC §12.1).
  - `promopilot.evals.Scenario` holds `name`, `group` (the nine §12.1 groups as slugs, such as
    `mid_plan_amendments`), `brief`, `as_of_week`, `seed`, `clarifications`, `amendments`,
    `labels` and `expect`. Unknown keys are refused.
  - `labels` are the planning-request fields the scenario states, all optional, as the final
    request should read them once the answers and amendments are in. #55 scores them.
  - `load_scenarios(dir)` loads every `*.yaml` in name order. A file's name must be its
    scenario's.
  - We rejected ordered steps like `cassettes/sessions.json`: every scenario would fix when the
    agent asks, so a legitimate variation in that would fail it.
- **D2. Answers are given when asked; amendments are made in order at Approval.**
  - `clarifications` maps a question id (the field name, ADR 0048) to an answer. It is given
    only when that question is asked, and again if it is asked again, for at most 3 rounds.
  - Each amendment is made once the session waits for approval, whatever the revision's status,
    an infeasible one included.
  - A question the scenario does not answer ends the run as `awaiting_clarification`, with no
    final plan. An error ends it as `failed`, with the error. The other runs go on.
- **D3. The runner drives the agent graph in process, through the entry points the API's
  session service drives it with.** This reads SPEC §7.2's "the eval harness drives sessions
  through the session API in process" loosely.
  - It calls `start_planning`, `resume_with_answers`, `resume_with_amendment` and
    `graph_state`, on an `InMemorySaver`. The session read model is not kept, and nothing is
    written to the app's database.
  - The final `PlanningState` holds the plan facts `validate_plan` needs (D7). The API's
    `SessionResponse` does not expose them, and `SessionService` needs Postgres.
  - It plays scripts as `record_cassettes` does (ADR 0054), but answers questions on demand
    and never approves.
  - We rejected driving `SessionService` against Postgres and polling it, which needs a new
    method to expose the facts and keeps the runner's tests out of the unit lane. We rejected
    HTTP through `ASGITransport`, which needs an API change as well.
- **D4. The eval plans on its own world.** `EvalWorld`:
  - generates the dataset from the datagen config and a world seed (42 by default, the world
    `make data` writes), in about 3 s;
  - fits demand, then relations on it, as of each scenario's week, with seed 42 as `make train`
    does, in memory, and keeps them for the rest of the run: 35–60 s per week on the seed-42
    world;
  - serves the tables through `promopilot.data.InMemoryRetailData`, with the clock fixed at the
    scenario's week. It moves out of the test fakes, which now subclass it;
  - scores with the oracle on the dataset's ground truth (ADR 0011).

  So a scenario can be planned at any as-of week from 1 to 104 without sales after it reaching
  the models (ADR 0008), and `make eval` needs neither `make data`, `make train` nor Docker. We
  rejected Postgres with the registered models, which pins every scenario to the models' week
  (104) and rules out the seasonal scenarios #56 needs.
- **D5. The planning stack is assembled in `promopilot.agents`.**
  - `planning_stack(demand, relations, data, *, policy, solver, simulation, seed, as_of_week)`
    returns the SPEC §9.6 tool registry, the default sequence and the planner agent's tools.
  - `PlanningSettings.from_settings(Settings())` reads the optimiser's budgets and seed, the
    simulation and the Critic's thresholds, and the settings a recording notes (ADR 0054). It
    replaces the code in `api/planning.py`, which now calls both.
  - So the API, `make record-cassettes` and the eval plan with the same tools in the same
    order, and a recorded planner turn replays in each. `evals` does not import `api`, which
    will import `evals` for `/api/evals/latest` (#57).
- **D6. A scenario's `seed` is its sessions' optimiser seed and simulation seed**
  (`PlanningSettings.seeded`). Every run of a scenario uses it, so the consistency metric
  (#53) measures the LLM's variation, not the seed's. The world seed is a run option, and every
  other planning setting comes from the environment as the app's do. The report records them.
- **D7. Constraint satisfaction checks each run's final plan revision** with
  `validate_plan(plan facts, the request it was planned on, company policy)` (ADR 0012).
  - Any violation fails the plan. The target is 100%.
  - An `INFEASIBLE` revision is not scored: its closest plan misses a clearance target by
    construction, and infeasibility handling scores it (#55). Nor is a run with no final plan.
    The report counts both.
- **D8. The oracle breach rate is the share of the same plans whose true outcome breaks a
  constraint**, reported with no target. Its breakdown counts each kind:
  - true promo cost over the budget (by more than a paisa);
  - true blended margin under the minimum, the brief's but never below the policy floor
    (`plan_limits`);
  - true demand above the available stock of any plan line, which is when the oracle caps it
    (ADR 0017).

  It never affects constraint satisfaction. We chose plans over plan lines, which ADR 0012
  also allows: a plan is what the manager approves.
- **D9. Expected properties are a closed vocabulary**, each a one-key mapping:
  - `asks_clarification: <field>`: the Context agent asked about it at some point;
  - `declares_infeasible: true|false`: the final revision's status;
  - `excludes_region: <Region>`: no final plan line in it;
  - `meets_clearance: <sku_id>`: no clearance shortfall for it.

  Any of the last three fails when there is no final revision. A failed property fails its run
  and scenario, and never touches the constraint metrics. #55 adds "relaxation touches", "no two
  strong substitutes" and "KVI response present".
- **D10. The report is a pydantic `EvalReport`**, written to `backend/evals/reports/`
  (gitignored) as `<UTC stamp>.json` and `.md`, such as `20260928T141503Z.json`, and as
  `latest.json` and `latest.md`.
  - The JSON is the model as it is, which #57 serves and generates frontend types from.
  - It holds the provider, the world seed, the planning settings and runs per scenario; each
    metric's value, count, target, direction, pass and breakdown; and per scenario and run:
    - the outcome, route, questions asked, amendments made and what fell back;
    - the final revision's summary;
    - the constraint check with its violations, and the oracle's figures with its breaches;
    - each property's result, and the run's duration.
  - The Markdown has the metric table, one row per run, and every failure.
  - Only `generated_at` and `duration_s` vary between identical runs, and
    `EvalReport.comparable()` leaves them out.
- **D11. `make eval` uses the provider `LLM_PROVIDER` names** (`build_provider(Settings())`), as
  spec #11 says: live if configured, otherwise replay. `.env.example` says `replay`.
  - Until #57 records cassettes for the eval scenarios, replay misses and the stack falls
    back: the Context agent reads by rules (ADR 0053), the planner runs the default sequence
    (ADR 0049), and the Explainer uses its template (ADR 0050). Each run's `fallbacks` says so.
  - A live run needs `LLM_PROVIDER=openai` set on purpose, and costs money.
- **D12. `make eval` runs `python -m promopilot.evals`** with `ONLY="a b"`, `RUNS=n` and
  `SEED=n`, and no `db` dependency. It exits 0 once the report is written, whatever the metrics
  say. It exits 1 for an invalid scenario, and 2 for an unknown name or no scenarios. #57 can add
  a flag that fails on missed targets for the CI smoke job.
- **D13. Three starter scenarios**, at week 104 with seed 0, mirror the recorded sessions:
  - `diwali-snacks-beverages` (the e2e brief);
  - `diwali-no-budget` (the clarify brief, answered "₹2 lakh");
  - `demo-budget-cut-drop-west` (the demo brief, amended twice).

  #56 grows the suite to 30. The runner's tests play 2–3 tiny scenarios on the small generated
  world, with models fitted once for the test session, and a down or scripted provider. So the
  only CI change is these unit tests in the backend job.

## Consequences

- **New public names:**
  - `promopilot.evals`: `Scenario`, `ScenarioGroup`, `RequestLabels`, the four properties,
    `load_scenario`, `load_scenarios`, `SCENARIO_DIR`, `EvalWorld`, `FittedModels`, `run`,
    `EvalReport`, `Metric`, `RunResult`, `RunOutcome`, `ScenarioResult`, `write_report`,
    `render_markdown`, `REPORT_DIR` and `ReportPaths`;
  - `promopilot.evals.metrics`: `check_constraints`, `oracle_breaches`,
    `constraint_satisfaction`, `oracle_breach_rate` and `check_property`;
  - `promopilot.agents`: `planning_stack`, `PlanningStack`, `PlanningData` and
    `PlanningSettings`;
  - `promopilot.data`: `InMemoryRetailData` and `RetailTables`.
- `make eval` is no longer a placeholder.
- There is no migration, no API contract change and no new configuration.
- On the seed-42 world, a run fits the models once per distinct as-of week (35–60 s each).
- **The first run** (`make eval`, replay, no key):
  - The three starter scenarios replayed the committed cassettes whole, with nothing falling
    back and the same routes as the recordings. So the eval's in-memory world and models ask
    the LLM exactly what the Postgres stack and the registered models asked.
  - It took about 10 minutes: 150–250 s per session, including the Critic's loop-backs and,
    for the first, the fit.
  - Constraint satisfaction was 2 of 2, and the oracle breach rate 2 of 2. Both e2e plans spend
    about 2% over the ₹2 lakh budget in truth and stock out on one line.
  - The demo's last revision (after "Drop West") is `INFEASIBLE`. It misses the 60% clearance
    target of SKU0006 in the North by a fraction of a point, so its `meets_clearance: SKU0006`
    fails. The recording ends there too. This is a finding for the target review (#58), not a
    harness fault.
