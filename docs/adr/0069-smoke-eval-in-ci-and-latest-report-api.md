# CI replays five tagged smoke scenarios across four weeks and fails on a session with no plan, a broken check or any cassette miss; the API serves the latest report as it was written

E9's #57 closes the loop on SPEC §12.3: "CI runs a 5-scenario smoke eval with `ReplayProvider`", and `/evals` reads the latest report. Reliability regressions must fail the build, with no key.

SPEC §12, spec #11 and #57 leave open:

- which five scenarios, and how they are chosen;
- what fails the build, and how that avoids flakiness;
- how the CI job is shaped, and how long it takes;
- where `GET /api/evals/latest` reads the report from, what it returns, and when it is 404.

We chose these with the owner on #57, taking every recommended option.

## Decisions

- **D1. The five smoke scenarios cover four as-of weeks and five groups.**

  | Scenario | Week | Group | What it proves |
  |---|---|---|---|
  | `diwali-snacks-beverages` | 104 | standard festive | the e2e brief to a plan (starter) |
  | `diwali-no-budget` | 104 | vague or conflicting | asks for the budget (starter) |
  | `infeasible-clearance-high-margin` | 50 | infeasible constraints | declares infeasible with a relaxation (AG-06) |
  | `amend-budget-cut-christmas-2025` | 62 | mid-plan amendments | re-plans after a budget cut, with a diff |
  | `price-war-bakery-beverages-offseason` | 82 | competitor price war | responds to undercut KVIs |

  - Every model history (ADR 0008) is fitted on Linux, which is where ADR 0054 D12's number drift would show.
  - It costs four fits (35–60 s each) and six planning rounds.
  - We left out scenarios that fail today: `demo-budget-cut-drop-west` misses SKU0006's clearance at 59.87% (ADR 0056), and `clear-curd-diwali-2025` and `cannibal-bakery-diwali-2026` failed in ADR 0065's first run.
  - We rejected two weeks (104 and 62; two fits, two histories) and week 104 alone (one fit, no amendment).
  - The three non-starters passed on fallbacks in ADR 0065's offline run. If one fails on its recording, a scenario of the same group takes its place.
- **D2. A `smoke: true` tag on the scenario file picks them.**
  - `Scenario.smoke` defaults to false.
  - `python -m promopilot.evals --smoke` plays only the tagged scenarios. `--smoke` with `--only` is refused (exit 2), as is `--smoke` with none tagged.
  - `make eval SMOKE=1` passes `--smoke`. `make eval-smoke` runs what CI runs: `LLM_PROVIDER=replay … --smoke --check`.
  - A suite test asserts exactly five tagged scenarios, in five groups, at all four weeks, with the infeasible, amendment and vague groups among them.
  - We rejected a name list in `ci.yml` or a `smoke.txt`: nothing would check its coverage, and it lives away from the scenarios.
- **D3. `--check` fails the run on what must never regress under replay, and never on a ratio metric.**
  - `promopilot.evals.check.report_problems(report)` lists, per run:
    - an outcome other than `planned` (failed, or still asking);
    - each violation of a final plan that fails its constraint check (ADR 0012);
    - each expected property that does not hold;
    - a vague or conflicting run that neither asked nor flagged, or an infeasible one not declared infeasible with a relaxation and a binding constraint (the 100% targets of ADR 0062);
    - every cassette miss, by request hash.

    A report with no scenario is a problem too.
  - With a problem, `--check` prints each one to stderr and exits **3**. Codes 1 and 2 keep their ADR 0056 D12 meaning.
  - `--check` needs `LLM_PROVIDER=replay` and no `--record`, and refuses otherwise (exit 2).
  - The ratio metrics are only reported: plan quality, regret, extraction, grounding, model recovery and WAPE. With five scenarios, one scenario moves a share by 20 points, and the targets are reviewed after the first full run (#58). An extraction mismatch never failed a run (ADR 0062).
  - A fallback the recording itself made (an ungrounded answer, a planner that ran out of steps) replays as recorded. It is not a problem.
  - We rejected reporting misses without failing: a prompt change that breaks replay would pass. We rejected failing every metric target: CI would be red until #58 closes the gaps.
- **D4. Each run lists its cassette misses.**
  - `RunResult.cassette_misses` holds the hash of every request replay held no cassette for, once each, in the order first asked. It covers every round, and the Critic too, not only the final round's `fallbacks`.
  - The runner wraps the provider of each run in `promopilot.evals.cassettes.MissLog`, which notes each `CassetteMissError` and raises it on. The stack falls back as before.
  - `CassetteMissError` gains `digest`, the missed request's hash.
  - A failing live LLM is not a miss.
- **D5. Flakiness.** Replay, the seeded world, the scenario seeds and the deterministic-time optimiser (ADR 0055) make a smoke run deterministic. Two sources of drift remain:
  - numbers that differ between Windows, where the cassettes are recorded, and Linux, where CI fits the models (ADR 0054 D12);
  - a wall-clock safety net that a slow runner reaches.

  Either shows as a miss, and the check names its hash. D12's remedy applies: drop or format the raw number in the request, and do not record on Linux. If misses flip between CI runs with no change, misses become report-only, as ADR 0054 D5 has it for `--check`.
- **D6. A new parallel CI job, `eval-smoke`.**
  - It runs on ubuntu-latest with setup-uv and its cache, then `uv sync --locked` and `LLM_PROVIDER=replay uv run python -m promopilot.evals --smoke --check`.
  - It needs no Docker, `make data` or `make train`: the seed-42 world is generated and fitted in memory (ADR 0056 D4).
  - `timeout-minutes: 45`. The expected runtime is about 22–28 minutes, estimated from the Windows timings.
  - Whatever the result, `latest.md` is appended to the job summary, and `backend/evals/reports/` is uploaded as the `eval-smoke-report` artifact for 14 days.
  - We rejected a step in the backend job, which would put 20+ minutes in series with the unit tests. We rejected the images job, whose image carries no `evals/`.
- **D7. `GET /api/evals/latest` reads `EVAL_REPORT_DIR/latest.json` on every request.**
  - `EVAL_REPORT_DIR` defaults to `evals/reports`, relative to `backend/`: the folder `make eval` writes. So `make dev` serves the host's latest run, and a new run shows at once.
  - The Docker stack mounts no report folder, so it answers 404. E10/E11 decide how the demo ships a report: a baked copy or a mount. We rejected a compose bind mount now: on a Linux host Docker creates the missing folder as root, which then breaks `make eval`.
  - We rejected storing reports in Postgres, which needs a migration for a file the eval already writes.
- **D8. It returns `EvalReport` as it is** (ADR 0056 D10), one source of truth for the report and the frontend types. We rejected a trimmed DTO: the dashboard needs the per-run detail too (spec #11, story 18).
- **D9. Both 404s have their own detail.**
  - With no `latest.json`: "No eval report yet: run `make eval`."
  - With a `latest.json` this version cannot read, such as one written before the report changed shape, or not JSON: "The latest eval report was written by another version of PromoPilot: run `make eval` again." It also logs a warning.
  - We rejected 500, which the dashboard can only show as an error, and serving the raw JSON unvalidated, which breaks the typed contract.
- **D10. The API imports only `promopilot.evals.report`**, as ADR 0056 D5 foresaw. `api/evals.py` holds `EvalReportService` and `evals_router`, which `create_app` takes as an optional `evals`. No API source file names the ground truth, so the boundary test holds.

## Merge order

The three non-starters replay from `backend/evals/cassettes/`, which the eval recording fills (ADR 0065, "Recording"). Until that recording is on main, they miss, and the smoke job fails by design. So the recording PR merges first, and this one is rebased on it. The two starters replay the app's committed cassettes and need nothing new.

## Consequences

- **New public names:**
  - `promopilot.evals`: `Scenario.smoke`, `RunResult.cassette_misses`, `InfeasibilityCheck.shortfall`, `promopilot.evals.check.report_problems` and `promopilot.evals.cassettes.MissLog`;
  - `promopilot.llm`: `CassetteMissError.digest`;
  - `promopilot.api.evals`: `EvalReportService`, `NoEvalReportError` and `evals_router`;
  - `Settings.eval_report_dir`.
- `python -m promopilot.evals` takes `--smoke` and `--check`, and exits 3 when the check fails. `make eval` takes `SMOKE=1`, and `make eval-smoke` is new.
- **API contract:** `GET /api/evals/latest` and the `EvalReport` schemas join `docs/openapi.json` and the frontend types.
- **New configuration:** `EVAL_REPORT_DIR`, in `.env.example`.
- There is no migration.
- The report JSON gains `cassette_misses` on every run. An older `latest.json` still validates, since the field has a default.
