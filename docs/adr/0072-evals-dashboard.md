# The `/evals` dashboard shows the latest report as it was written: grouped metric cards with the report's own pass or fail, a sorted and clipped regret chart, and a scenario table whose "trace" is each run's detail in the report

E10's #66 gives judges the D2 evidence (SPEC §11, §12.3; spec #12, story 22). `/evals` reads `GET /api/evals/latest` (ADR 0069). It shows metric cards against their targets, a per-scenario pass/fail table "with links to session traces", and a regret distribution chart.

#66 leaves open:

- how the cards are grouped, and how pass, fail, report-only and n/a metrics show;
- the table's rows, columns and filters;
- what a "link to a session trace" can point to, when eval sessions are never stored;
- the chart's form for a signed regret with outliers of −1076% and +241%;
- the empty and error states, the provenance line, the demo stack's report and the Playwright scope.

We chose these with the owner on #66, taking every recommended option.

## Decisions

- **D1. Cards are grouped by metric name, in five groups**, each keeping report order within it:
  1. Constraints;
  2. Agent behaviour;
  3. Plan quality;
  4. Model recovery;
  5. Latency and cost.

  A name the map does not know goes under **Other**, so a metric the report adds later still shows. A line above the groups counts the targets met out of those the report judged.
  - We rejected one flat grid, which hides the D2 story, and grouping by unit.
- **D2. Every badge is the report's own `passed`.**
  - **Pass** or **Fail** when the report judged the metric.
  - **Reported** for a metric with no target. It shows "Report · aim ≤ 25%" when it has an `aim`, and never judges it.
  - **Not scored** when `value` is null. The value reads "n/a" and the target still shows.

  Each card shows the value, the target, "count of of" when `of` is set, and its breakdown as chips. The dashboard never compares a value with a target itself.
- **D3. Units.**
  - A share is a signed percentage to one decimal at most (`formatShare`), so a negative regret reads as one.
  - A P50 in seconds is a duration (`formatDuration`), e.g. "2 min 29 s".
  - Rupees keep their paise (`formatPrice`), e.g. "₹3.04": `formatMoney` would round a session's cost to ₹3. This is ADR 0057 D6's rule for LLM cost.
  - Money in the run detail (oracle objectives) follows ADR 0060 D7 (`formatMoney`).
- **D4. Every eval number is a `SourcedNumber` whose source is `make eval · <metric name>`**, with "count of of" as its detail (SPEC §11 UX rule). Per-run figures name the metric they feed: `regret`, `session_latency_p50`, `session_cost_p50` or `plan_quality`.
- **D5. `RunResult.passed` is written into the report.**
  - It was a plain property, so the JSON carried only each scenario's result, and the dashboard would have had to re-derive a run's.
  - It is now a pydantic `computed_field`, so `/api/evals/latest` serves it. The contract and the frontend types are regenerated.
  - An older `latest.json` still validates, because a computed field is output only.
  - We rejected re-deriving it in the frontend, which copies the pass rule, and showing only the scenario's result.
- **D6. The table has one row per scenario, in report order.**
  - **Columns:**
    - Scenario, Group (its SPEC §12.1 name), Week and Result (the scenario's `passed`);
    - then the last run's Outcome and Constraints;
    - its oracle breaches;
    - its properties passed out of expected;
    - how it did against the rule-based baseline;
    - its Regret, Time and Cost.
  - A run's fallbacks and cassette misses show as warning badges under the result.
  - **Details** opens every run of the scenario, so a multi-run report needs no second expander.
  - We rejected one row per run, as the Markdown has it: 32 × `RUNS` rows buries the scenario results.
- **D7. Filters: a Failed only toggle and a Group select.** There are no sort controls, as in ADR 0060 D12.
- **D8. #66's "links to session traces" means each run's detail in the report.**
  - An eval run is an in-memory session with no id in the app's database (ADR 0056 D3), so there is no `/sessions/[id]` to link to.
  - **Details** shows the trace as the report holds it:
    - the route (the graph nodes and interrupts);
    - the questions asked, the amendments applied and the flagged fields;
    - the fallbacks and cassette misses;
    - the final plan revision;
    - the oracle objective against the rule-based and the best plans, with the regret in rupees;
    - every violation, and each property with its detail.
  - A **Scenario YAML** link opens the scenario's file on GitHub (`main`), which may be newer than the report.
  - We rejected storing eval sessions in the app's database, which needs a migration and a new write path.
- **D9. The regret chart has one bar per scored run, sorted from lowest to highest regret.**
  - The y-axis stops at ±100%. A bar beyond it is drawn at the edge in a darker shade, and the legend says so.
  - The legend and reference lines show the report's median (the `regret` metric's value, never recomputed) and the target.
  - Tick labels are shortened. The tooltip and **Show values** give each run's full name and exact value, and mark the clipped ones.
  - Runs with no regret (no scored plan, or an infeasible best plan) are counted under the chart.
  - It is tested through its values table, as ADR 0068 D2 has it.
  - We rejected a histogram, which hides which scenario sits where, and an unclipped axis, which flattens every bar but two.
- **D10. States.**
  - **A 404 is the empty state, not an error.** It shows the API's own detail, which covers both of ADR 0069 D9's 404s, and a hint: `make eval` for the suite, `make eval SMOKE=1` for the five smoke scenarios, and where the page reads `latest.json`. It is not retried.
  - **Any other failure** retries twice, then shows the shared `ErrorMessage` with its reference id (ADR 0071) and a **Retry** button.
  - **Loading** shows "Loading the eval report…".
- **D11. The provenance line** gives when the report was generated, the provider, the world seed, and scenarios × runs. **Planning settings** fold out below it.
  - The report does not say whether it was a smoke run, so the page shows no smoke or full badge. We rejected inferring one from the scenario count.
- **D12. The composed stack still has no report.** How the demo ships one, as a baked copy or a mount, is left to E11's #72 (ADR 0069 D7).
- **D13. Tests.**
  - **Vitest**, from a trimmed copy of the recorded full run (`tests/unit/fixtures/eval-report.json`), covers:
    - the client, whose 404 is an answer and not an error;
    - the cards, against their targets;
    - the table and its filters and details;
    - the chart's values;
    - the page's states.
  - The fixture keeps every metric and eight scenarios: passing, a failed property, a failed constraint, an infeasible revision, a vague brief that asked, an infeasible brief and two regret outliers. It gains one invented cassette miss.
  - **Playwright**: one spec opens `/evals` from the nav on the composed stack and checks the empty state, since that stack answers 404.
- **D14. The zod schema validates only the fields the dashboard reads**, and each part `satisfies` the generated type, so a contract change that breaks the page fails `tsc`.

## Consequences

- **New public name:** `RunResult.passed` is serialised; `docs/openapi.json` and `schema.d.ts` gain it. There is no migration and no new configuration.
- **Frontend:**
  - `/evals`, and **Evals** in the header;
  - `lib/api/evals.ts` (`getLatestEvalReport`, `evalReportSchema`) and `lib/eval-metrics.ts`;
  - the `EvalMetricCards`, `EvalScenarioTable`, `RegretChart` and `EvalsView` components.
- The table fits at 1280 px and above (SPEC §11).
