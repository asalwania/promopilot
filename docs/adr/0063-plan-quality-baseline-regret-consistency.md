# Plans are measured against a rule-based baseline and our own optimiser on true parameters, both built by the harness from each run's final request, and runs of a scenario against each other

#53 adds three SPEC §12.2 metrics to the eval report (ADR 0056):

- **plan quality**: beats a rule-based baseline, "20% off top 10 sellers", in at least 90% of scenarios;
- **regret**: against the "optimiser run on true parameters", median at most 10%;
- **consistency**: the same scenario run 5 times, with a Jaccard overlap of the selected SKUs of at least 0.9.

SPEC §12, #11 and #53 leave open how both comparison plans are built, what regret measures and in what units, what "beats" means with several runs, how the Jaccard is taken, and what the 5 runs cost. We chose these with the owner (D1–D15 on #53, every recommended option).

## Decisions

- **D1. The harness builds both plans from each run's final planning request**, never from anything a scenario author writes. The final request has every answer and amendment in it, and is complete. Both are cached per (scenario seed, request), so the runs of a scenario that plan on the same request share them.
- **D2–D4. The rule-based baseline**
  - The top 10 SKUs in the request's scope (its categories, and its SKUs if it names any) by units sold in every store of its regions over the 12 weeks before the as-of week. Ties go to the lower SKU id.
  - Each is promoted in every region of the scope: PCT_OFF 20%, to All customers, from the start of the promo window. It ignores stock, the margin floor, the category cap, clearance targets and KVIs: it is the naive rule, and the oracle caps demand at stock anyway.
  - It fits the budget on plan-time numbers, as the planner's plans do (ADR 0012): each line's expected promo cost on the scenario's fitted demand model. Whole sellers, in every region at once, are dropped from the bottom until the total fits the marketing budget and every regional cap. The empty plan is allowed.
  - **Deviation from D3:** the window was to be covered by back-to-back lines of at most 4 weeks. A plan has at most one line per SKU and region, so a window longer than 4 weeks is covered for its first 4.
- **D5–D6. The best plan is our own optimiser on true parameters.**
  - `promopilot.evals.truth_forecast` answers the demand model's (`predict`, `line_paths`, `baseline`) and relations model's (`substitutes`, `complements`) interfaces from the ground truth. `TrueForecast` predicts each option alone with the oracle's true demand function, over the promo weeks and the pull-forward weeks after them, at the true competitor prices. `TrueRelations` lists the true pairs, each partner with the true effect of the SKU's price on it.
  - They replace the fitted models in the option context a session would load at the request's as-of week (stock, competitor gaps, catalogue). `generate_options` and `solve` then run unchanged, with the session's deterministic work budgets (ADR 0055) and the scenario's seed, and the binding analysis off.
  - P90, which the stock rule prunes on, comes from the true negative-binomial noise of store-level sales: std = √Σ(μ + μ²/r) over store × week × segment. There is no parameter uncertainty, but sales noise stays, so the best plan faces the same stock rule ours does.
  - `TrueDemand.expected_units` takes an optional SKU subset (`sku_ids`), so a line is predicted on its own SKUs' columns. The other SKUs are at their reference price and move nothing.
  - We rejected scoring each fitted-pipeline option with the oracle itself: about 17,000 single-line evaluations per request, with pairwise terms still needing a source.
- **D7–D9. Regret**
  - Oracle profit is the oracle's objective: incremental profit plus clearance value (ADR 0005), for the baseline comparison and regret alike. The best plan is scored by the oracle too, not by its own objective, so all three plans are compared on the same numbers.
  - Regret = (best − ours) / best. It is signed and not clipped: a plan that beats the best plan's approximations (pairwise terms, stock caps, true spend over budget) shows below 0. The rupee gap is kept next to it.
  - When the best plan earns ₹0.01 or less, regret is 0 if ours earns at least as much (within a paisa), else 1.
  - A run is left out when its own plan is not scored (infeasible or no plan). So is one whose best plan is `INFEASIBLE` in truth, counted as `best_infeasible`.
- **D10–D11. Metric values**
  - Regret is the median over scored runs. Its count is the runs within 10%.
  - Plan quality is per scenario. A scenario beats the baseline when every scored run beats it by more than a paisa; one with a losing run loses; the rest tie. Scenarios with no scored run are left out, and the breakdown counts each verdict.
- **D12–D13. Consistency**
  - Per scenario: the mean Jaccard over every two runs with a final revision (any status). Each run's set is the SKUs its revision promotes, BUNDLE partners included, whatever the region. Two empty sets agree completely.
  - The metric is the mean over scenarios with at least two such runs. Its count is the scenarios at 0.9 or more.
  - It uses the `RUNS` runs the eval already plays. `make eval` keeps 1 run by default, so consistency is not scored (n/a) and the report says to run `make eval RUNS=5`.
  - Under the replay provider a scenario's runs are identical: each plans with the scenario's seed (ADR 0056 D6). So consistency measures something only with a live LLM.
- **D14. Targets.** Plan quality ≥ 90%, regret median ≤ 10%, consistency ≥ 0.9, each with pass or fail. `Metric.value` may now be negative or above 1 (regret).
- **D15. The report** keeps, per scored run:
  - our objective;
  - the baseline's sellers kept and dropped, lines, expected promo cost and objective;
  - the best plan's status, lines, SKUs and objective;
  - the verdict, regret and rupee gap.

  Each revision summary lists its SKUs, and each scenario its consistency. The Markdown adds a plan-quality table.

## Consequences

- **New public names:**
  - `promopilot.evals.quality`: `rule_based_plan`, `RuleBasedPlan`, `best_plan`, `Benchmarks`, `assess`, `regret`, `jaccard`, `mean_pairwise_jaccard`, `scenario_consistency`, `plan_quality`, `regret_metric` and `consistency`;
  - `promopilot.evals.truth_forecast`: `TrueForecast` and `TrueRelations`;
  - `promopilot.evals.report`: `RuleBasedSummary`, `BestPlanSummary` and `PlanQuality`;
  - `EvalWorld.dataset`.
- **Additive changes:** `RunResult.quality`, `ScenarioResult.consistency` and `RevisionSummary.sku_ids`.
- There is no migration, no API contract change and no new configuration.
- On the small test world, the best plan's own objective is within 0.1% of the oracle's score of it. That is the check that it plans on the true demand. It also beats the plan the fitted models choose for the same request.
- **Timing,** on the seed-42 world for the e2e request (Snacks and Beverages, North and West, weeks 108–109, ₹2 lakh):
  - the rule-based baseline takes about 1.4 s;
  - the best plan takes about 29 s: true-parameter option generation, then an OPTIMAL solve over 1,923 eligible options;
  - both are paid once per distinct (seed, request).
- **The first run** (`make eval`, replay, the three starter scenarios) took 642 s against ADR 0056's "about 10 minutes":
  - the two Diwali scenarios end on the same request and share one computation;
  - the demo's final revision is infeasible, so it is not scored.

  The results:
  - both scored plans (₹1.43 lakh by the oracle) beat the baseline (5 of its 10 sellers fit the budget, and it loses ₹63,025 in truth);
  - regret is 9.3% against the best plan's ₹1.58 lakh (35 lines);
  - plan quality is 2 of 2 and median regret 9.3%, both passing;
  - consistency is not scored at one run.
- **At 30 scenarios** (#56), the benchmarks add about 30 s for each distinct request, roughly 15 minutes. `RUNS=5` multiplies session time by 5 but not the benchmarks.
- **#57's smoke eval** gains about 30 s per distinct request.
- The runner's unit tests on the small world gain a few seconds, at about 3 s per best plan.
