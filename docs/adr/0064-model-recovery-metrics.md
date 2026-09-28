# Model-recovery metrics read the eval world's own fit at its default week and report elasticity error, pair detection and the holdout WAPE

#54 adds the evidence that the models learned the truth (SPEC §12.2):

- elasticity recovery, as the median absolute % error against the true own-price elasticity, with a target of ≤ 20%;
- substitute and complement detection, as precision and recall against the true pairs, with targets of ≥ 0.8 and ≥ 0.7;
- baseline forecast WAPE on the 12-week holdout, reported with an aim of ≤ 25%.

The ticket says to read them "from the registered models and ground truth". SPEC and the ticket leave open:

- which models and which week;
- the grain and the error definition;
- what counts as a detected pair;
- where WAPE comes from and at which grain;
- how a report-only aim shows;
- where the metrics run, and what a failed fit does.

We chose these with the owner (D1–D9 on #54; every recommended option).

## Decisions

- **D1. The metrics read the eval world's own fit at its default as-of week, with the world's ground truth.**
  - The default week is the first week after the generated history: `history_weeks`, which is 104.
  - The world fits with the same seed as `make train` (42). So these are the models `make train` registers after `make data` for the same world, but they come without Postgres or the registry, as ADR 0056 D4 has the eval do.
  - `EvalWorld` gains `default_as_of_week`, `ground_truth` and `fitted(week)`. `models(week)` now serves what `fitted` returns.
  - The starter scenarios already fit week 104. A run with no scenario at that week fits it once more (35–60 s).
  - We rejected a set of metrics per scenario week, which gives more rows and a less clear headline. We also rejected Postgres with `ground_truth.json`, which needs `make data`, `make train` and Docker, and could compare one world's models with another's truth.
- **D2. Elasticity recovery covers every SKU × segment β.**
  - It takes every β row of `DemandModel.coefficients()`, including terms that took the subcategory prior because the SKU's history never exercised them.
  - The error is |β̂ − β| / |β|, and the metric is its median.
  - A zero truth raises. Datagen bounds β to [−3.5, −0.5], so none occurs.
  - `count` is the number within 20%, and `of` is the number compared.
  - A true elasticity with no estimate raises.
  - This is the measure ADR 0024 holds the model to.
- **D3. A detected pair is one the relations model keeps.**
  - The eval calls `substitutes(sku)` and `complements(sku)` for every catalogue SKU and normalises each result to an unordered pair. The model fits one symmetric θ per pair, and datagen stores each true pair once with the same sign both ways.
  - Complements kept on basket lift alone, where θ is not estimable, count.
  - Precision is over every detected pair in the catalogue. Recall is over every true pair, including pairs whose prices never moved.
  - We rejected rebuilding detections from `cross_effect()` with our own threshold, which measures θ rather than the rule the planner uses. We also rejected recall over testable pairs only, which flatters it.
- **D4. Four detection rows**: substitute precision, substitute recall, complement precision and complement recall.
  - Each row has its own target and pass/fail.
  - `count` is the true positives, and `of` is the detected pairs (for precision) or the true pairs (for recall).
  - A row with `of` = 0 is n/a.
- **D5. Baseline WAPE is the demand model's own holdout WAPE** from `DemandModel.metrics`.
  - The model is fitted before `as_of − 12` and scored on the clean rows of the last 12 weeks, then refit on all history (ADR 0023). No ground truth is needed.
  - The private `_wape` becomes the public `promopilot.models.demand.wape(units, predicted)`, which raises when there are no units. It has hand-computed tests.
  - We rejected a forward WAPE against the oracle's true no-promo mean, which is not the SPEC §9.1 definition.
- **D6. Three report-only WAPE rows**, at the three grains ADR 0023 reports:
  - `baseline_wape` (store × SKU × segment);
  - `baseline_wape_store_sku`;
  - `baseline_wape_region_sku` (the plan-line grain).

  Showing only the best grain would look like cherry-picking. The model reports no count for its WAPE, so `count` = `of` = 0, and the Markdown and the CLI leave the count out when `of` is 0.
- **D7. `Metric.aim`**: an optional value a reported metric aims for, in its `direction` and `unit` (ADR 0062), and never judged.
  - WAPE sets `aim` to 0.25 with direction `at_most`. `target` and `passed` stay None.
  - The Markdown shows "report (aim ≤ 25%)", and the CLI summary shows "(aim 25%)". Targets and aims are formatted in the metric's unit by `format_amount`, which `format_value` also uses.
  - We rejected setting `target` with `passed` None, which reads like "nothing was scored". We also rejected putting the aim in the label, where the dashboard cannot read it.
- **D8. The metrics are computed once per report inside `run()`**, after the scenarios, and appended after the existing metrics.
  - This keeps `run()`'s report complete (spec #11, seam 1).
  - The runner tests now look metrics up by name, so #53 and #55 can append theirs.
  - There is no new CLI flag.
- **D9. A failed fit raises.** The eval world always fits, so a missing model can only be a bug, and every scenario at that week would fail too.

## Consequences

- **New public names:**
  - `promopilot.evals.recovery`: `recovery_metrics`, `elasticity_recovery`, `median_abs_pct_error`, `precision_recall`, `detection` and `baseline_wape`;
  - `promopilot.models.demand.wape`;
  - `EvalWorld.default_as_of_week`, `EvalWorld.ground_truth` and `EvalWorld.fitted`;
  - `Metric.aim` and `promopilot.evals.report.format_amount`.
- There is no migration, no API contract change and no new configuration.
- The report gains eight metrics. #57 serves them as they are.
- **First run** (`make eval`, replay, seed-42 world, as of week 104): every target is met.
  - Elasticity recovery was 8.1%, with 679 of 800 SKU × segment estimates within 20%.
  - Substitutes: precision 0.867 (91 of 105) and recall 1.00 (91 of 91).
  - Complements: precision 1.00 (39 of 39) and recall 0.975 (39 of 40).
  - Baseline WAPE was 43.5% at the model grain, 25.1% at store × SKU and 13.5% at region × SKU.
  - The recovery metrics added no fit, because the three starter scenarios already fit week 104.
