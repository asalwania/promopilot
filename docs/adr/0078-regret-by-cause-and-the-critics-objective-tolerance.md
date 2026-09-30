# Regret splits into model error, the planner's choices and timeouts against the default plan; a timed-out best plan is not counted; and the Critic keeps a risk-reducing attempt only within 5% of the best objective

#157 comes from #58's target review of the first full eval run. Median regret was 23.5% against SPEC §12.2's target of 10% or less. Seven scenarios were above 60%. Five were negative, because the "best" plan itself had timed out as FEASIBLE.

The ticket asks to:
- split each scored run's regret into model error, the planner's choices and timeouts;
- flag negative regrets from a timed-out best plan;
- fix the largest cause.

SPEC and ADR 0063 leave open:
- what each part is measured against, and how the parts add up;
- when a part counts as a timeout;
- what "flagged" means for the metric;
- which fix.

We chose these with the owner at #157's decision gate (D1–D7, every recommended option).

## What the gate measured

The gate replayed every scored scenario offline (`LLM_PROVIDER=replay`, the committed cassettes, main 407873a, the seed-42 world). For each run it also solved the final request with the default sequence on the scenario's fitted models: the **default plan**.

On the 29 scored runs the replay's median regret was 22.6%.

| Part | ₹ lost (runs with every plan OPTIMAL) | Runs above 10% where it is the largest part |
|---|---|---|
| The planner's choices | ₹1.99 lakh | 6, among them 4 of the ~70% runs |
| Model error | ₹1.32 lakh | 9 |
| Timeouts | — | 1 (and all 5 negative or undefined regrets) |

**The planner's choices come from the Critic loop.** In 9 of the 10 scenarios where the planner's part is not zero:
- the Critic sent the plan back for over-concentration or heavy cannibalisation;
- the planner left SKUs out or capped the promoted SKUs;
- `critic.best_attempt` preferred the attempt with fewer risk findings over the one with the higher objective (ADR 0051 D7).

The chosen attempt gave up 6.6%–63.7% of the plan-time objective of the first attempt, which is the default plan. For example:

| Scenario | Regret | Planner part | Plan-time objective given up |
|---|---|---|---|
| tight-diwali-2025-snacks | 71.6% | 66.6 points | 60.5% |
| tight-christmas-2025-bakery | 69.8% | 60.5 points | 63.7% |
| cannibal-bakery-diwali-2026 | 70.7% | 56.1 points | 62.3% |
| durga-puja-2025-east | 23.5% | 22.3 points | 22.2% |

The tenth scenario, `diwali-2026-staples-dairy-margin`, had 76.9 planner points. Its brief said "Target families", and the planner narrowed to that segment. A planning request cannot hold a segment, so the default and best plans ignored it: the gap was in the benchmark, not the planner.

**Model error is the optimiser's curse.** Over every option of a request, the fitted and true values agree. On the options the optimiser selects, the fitted value is inflated, for example ₹1.17 lakh against ₹73.3k. The default plan's own median regret is 8.9%. #170 follows it up.

**Timeouts.** The best plan was FEASIBLE in 5 runs, giving regrets of −1,076%, −706%, −37%, 1.0 and 0.0. With 60 deterministic seconds the first three become OPTIMAL. #156 turns clear-curd's best plan `INFEASIBLE` and gives empty timed-out plans the greedy plan. It does not touch the three negative runs.

**Counterfactual medians:**
- flagging timed-out best plans: 23.6% (24 runs);
- also restoring the default plan in the 9 Critic-loop scenarios: **10.6%**.

#158's guard, which the best plan shares, moves cannibal-bakery from 70.7% to 23.7% on its own.

## Decisions

- **D1. Regret splits into three signed shares of the best plan's oracle objective, which sum to the regret** (`quality.regret_breakdown`).
  - **Model error** = (best − default) / best. It is the same `generate_options` and `solve` on the fitted models against the true parameters, for the same request, seed and work budgets.
  - **Planner** = (default − ours) / best. It is the planner agent's plan (with the Critic loop) against the default sequence's.
  - **Timeouts.** A part moves here when either of its two plans is FEASIBLE: the solver stopped on its work budget before proving it OPTIMAL.
    - The model-error part moves when the best or the default plan timed out.
    - The planner part moves when the default plan or ours timed out.
  - The breakdown is None in three cases:
    - the best plan earns a paisa or less (ADR 0063 D9's 0-or-1 regret is not a share);
    - the best plan is `INFEASIBLE`;
    - the default plan is `INFEASIBLE`.
  - The **default plan** is `quality.default_plan`: `best_plan` with the fitted models. The binding analysis, which only explains a plan, stays off. `Benchmarks` computes it once per (seed, final request), with the baseline and the best plan. The gate measured a median of 41 s for it.
  - We rejected measuring timeouts by re-solving each FEASIBLE plan with a longer budget. That took 52–1,417 s per re-solve at the gate, and the parts would no longer sum exactly.
- **D2. A run whose best plan timed out is flagged and left out of the regret metric, whatever its sign.**
  - `PlanQuality.timed_out` lists which of `best`, `default` and `ours` stopped as FEASIBLE.
  - The regret metric's median covers scored runs whose best plan is feasible and did not time out.
  - Its breakdown adds `best_timed_out` next to `best_infeasible`. For each counted run above the target, it also counts the largest part: `largest_model_error`, `largest_planner` or `largest_timeouts`.
  - The Markdown writes such a run's regret as "(best timed out: not counted)".
  - We rejected leaving out only negative regrets: a timed-out best plan understates every regret, not just the negative ones. We also rejected re-solving the best plan with a longer budget in the eval, for the cost above.
- **D3. The fix: the Critic's best attempt keeps a risk-reducing attempt only within an objective tolerance** (`critic.best_attempt`). This amends ADR 0051 D7. It:
  1. keeps the attempts with the fewest violations, as before;
  2. among them, keeps those whose plan-time objective is within `CRITIC_OBJECTIVE_TOLERANCE` (a share) of the highest one's;
  3. among those, takes the fewest risk findings, then the highest objective. A tie goes to the later attempt, as before.

  An attempt with no objective is never ruled out by it. So leaving a flagged SKU out goes on only when it costs at most that share. Otherwise the earlier plan goes on, and its risk findings stay as open issues (ADR 0051 D3).
  - The loop itself is unchanged: the same findings go back, with the same feedback, at most 3 times. So no planner or Critic request changes.
  - We rejected looping back only on violations and stock-out risk (the planner never sees the other findings, and AG-04 narrows further). We also rejected a planner prompt that discourages narrowing, which misses every planner cassette and has an uncertain effect. The model-error fix (#170) is left to after #158 and #73.
- **D4. The tolerance is 5%, and a stock-out risk counts like any other risk finding.**
  - The smallest loss the gate saw was 6.6%, so every Critic-driven loss it saw is above the tolerance. On the small test world, leaving SKU0004 out gives up 5.2%, so that test's flagged plan now goes on.
  - The tolerance is a setting, `CRITIC_OBJECTIVE_TOLERANCE` (default 0.05, 0–1). It is part of `RiskThresholds` (`objective_tolerance`) and of the settings a recording notes (`RECORDED_SETTINGS`, ADR 0054). `.env.example` and the README list it.
  - We rejected always preferring an attempt that lowers stock-out risk, 0% (objective first) and 10%.
- **D5. `diwali-2026-staples-dairy-margin` drops "Target families."** Its labels are unchanged, since no label read the segment. That scenario's recording is redone.
  - We rejected keeping it and documenting the benchmark gap: 77 points of regret would stay that no plan could remove.
- **D6. The report carries the new fields, and the dashboard waits.**
  - `PlanQuality` gains `default` (`DefaultPlanSummary`), `breakdown` (`RegretBreakdown`) and `timed_out`. All three are optional, so a report written before this ADR still reads.
  - The Markdown's plan-quality table gains Default sequence, Model error, Planner and Timeouts columns. Under it, one line gives each part's median over the counted runs and its rupees in all.
  - `make api-types` regenerates the frontend types. `/evals` shows nothing new (#171).
- **D7. Sequencing.** This lands on main before #156 and #158 merge and rebases after each. The main session records the app sessions and the smoke scenarios for this PR. It then re-records all 32 scenarios once #156, #158 and this PR have merged.

## What this amends

- **ADR 0051 D7:** the best attempt is no longer "fewest violations, then fewest risk findings, then the highest objective". Fewer risk findings win only within the objective tolerance.
- **ADR 0063 D9–D10:** a run whose best plan timed out is left out of the regret metric, like one whose best plan is infeasible. `PlanQuality` carries the default plan and the breakdown, and `Benchmarks.assess` takes our plan's solver status.

## Consequences

- **New public names:**
  - `promopilot.evals.quality`: `default_plan` and `regret_breakdown`;
  - `promopilot.evals.report`: `DefaultPlanSummary`, `RegretBreakdown` and `TimedOutPlan`;
  - `RiskThresholds.objective_tolerance`, and `promopilot.guardrails.within_objective_tolerance`, which does the tolerance's arithmetic outside the agents package (ADR 0049 D10);
  - the `CRITIC_OBJECTIVE_TOLERANCE` setting.
- `critic.best_attempt` takes `objective_tolerance`, and `quality.assess` takes `status` and `default`.
- There is no migration. The OpenAPI contract gains optional fields, and the frontend types are regenerated.
- **LLM requests.**
  - No prompt, tool description or planner or Critic request changes.
  - Where the loop chose an attempt with fewer findings that gave up more than 5%, the revision that goes on is now another one. That revision's Explainer request, and every later round's requests after an amendment, change and miss.
  - The recorded-settings fingerprint gains `critic_objective_tolerance`, so `make check-cassettes` reports a settings mismatch until `make record-cassettes` runs.
  - The staples-dairy brief changes, so its whole session misses.
  - The PR lists the exact misses of an offline `--check` replay. The main session re-records, with the owner's OK.
- **Eval time:** the default plan adds about 20 minutes to a full `make eval`, once per distinct request.
- **Tests:**
  - the breakdown by hand (the parts, their signs and sum, each timeout case, and the None cases);
  - the metric's `best_timed_out` exclusion and largest-part counts;
  - the Markdown row and summary line;
  - the default plan equal to the fitted default sequence's solve;
  - the Critic's tolerance through the graph: an attempt 6% worse loses, one 5% worse wins, the setting moves it, and fewer violations still win at any objective;
  - the setting's validation, default and recording.
- **Follow-ups:** #170 (model error: an uncertainty-shrunk objective) and #171 (the breakdown on `/evals`).
