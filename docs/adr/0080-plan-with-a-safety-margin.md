# Plans keep a safety margin: the budget counts P90 promo cost, stock holds expected units plus 2σ, the margin holds at units' P10; the oracle breach rate gets a 15% target

#159 comes from #58's target review of the first full eval run. Judged by the oracle on true demand, 12 of 29 plans broke a limit:
- 7 overspent the promo budget;
- 7 sold more than the stock;
- 2 fell below the minimum margin.

The latest smoke consistency run broke one in 6 of 12. The optimiser planned on expected values with no safety margin. ADR 0012 had kept the oracle breach rate without a target and rejected constraining spend and margin at P90. ADR 0005 had capped expected promo cost only.

The ticket asks to plan with a margin (budget against a high quantile of promo cost, stock with a buffer, margin against a low quantile), to make it configurable, and to give the oracle breach rate a target agreed with the owner.

We chose these with the owner at #159's decision gate (D1–D10, every recommended option).

## What the gate measured

The gate ran offline, with no LLM, on the seed-42 eval world. It took the final requests of the 27 distinct scored scenarios, from their labels. For each it:
- generated the options on the fitted models;
- solved with the session's work budgets, the binding analysis off and the scenario's seed (the default sequence);
- scored the plan with the oracle, against the unchanged request.

**Default plans breach in 13 of 27 (48%):** the budget in 10, stock in 6, the margin in 1.

**Why.** Every plan that breaks the budget spends 99.9–100% of it on expected cost. So any error upwards breaks it: true spend was 0.3% to 15.8% over.
- Per selected line the fitted units are unbiased (median error +0.3%).
- But 15% of lines, not 10%, sell more than their P90: the z at the 90th percentile is 1.69, not 1.28.
- The demand model's `units_std` holds parameter uncertainty and demand noise, but not the baseline forecast's error (region WAPE 13.5%).
- Errors are correlated across a plan's lines. The plan-level cost error ran from −13% to +18%, where independent lines would give 2–3%.

**Stock breaches come from the model's own error.** On every line that breaks stock, the true demand of that line alone exceeds its fitted P90, always with the fitted baseline too low. The joint evaluation's cross effects do not cause it. The optimiser packs lines up to P90 = stock: 120 of 563 selected lines had P90 at 90% or more of their stock.

**Rounding plays no part.**

Offline effect, over 26–27 scored plans. "Profit" is total oracle profit against the default plans. Regret is the median against a best plan solved with the same margin.

| Variant | Breaches (budget / margin / stock) | Profit | Regret |
|---|---|---|---|
| none (before) | 13/27 (10 / 1 / 6) | — | 7.8% |
| budget P90 only | 6/26 (1 / 1 / 5) | −3.0% | 8.7% |
| stock k = 2 only | 11/27 (10 / 1 / 3) | −2.2% | 10.6% |
| margin P10 only | 12/27 (10 / 0 / 6) | −0.3% | — |
| **budget P90, stock k = 2, margin P10** | **4/26 (2 / 0 / 3)** | **−5.2%** | **10.3%** |
| same with stock k = 2.5 | 2/26 | −9.0% | 11.7% |

- Every variant still beats the rule-based baseline in every scored scenario.
- Stock-outs cost little in oracle profit, since the oracle only caps sales. Every stock buffer therefore buys the metric with real profit.

## Decisions

- **D1. The budget counts each option's promo cost at a quantile: P90 by default.**
  - Discount funding moves with units, and the fixed marketing cost does not. So promo cost's std is each SKU's discount funding × its units' coefficient of variation, a BUNDLE's partner included.
  - The budget row's coefficient is cost + z × std, with z = Φ⁻¹(quantile). The same applies to each regional cap.
  - Summing per-line P90s is conservative: the simulator's plan P90 is at most the sum. That suits the correlated errors the gate found.
  - We rejected a flat budget haircut (not a quantile, and no better: 7 breaches) and a post-solve simulate-and-tighten loop (extra solves, no better).
- **D2. Stock holds expected units plus k standard deviations: k = 2 by default.**
  - k is never below 1.2816, the P90 rule.
  - A line must fit both its P90 units and its buffered units, and so must a BUNDLE's partner.
  - We rejected a buffer as a fraction of stock (−6.6% profit for the same breaches), k = 2.5 as the default, and calibrating the std with the baseline's error: that is a model change, left to #170 or a model ticket.
- **D2-where. The buffer applies where the solver decides what is eligible, not in option generation.**
  - Generation still prunes at P90, so the `generate_candidates` output and every planner request before the optimiser are unchanged.
  - A buffered-out option is not selected, with reason `out_of_stock`.
- **D3. The minimum margin holds with units at a quantile: P10 by default.**
  - Each line's shortfall m × revenue − gross profit is scaled by 1 + z × cv where the line is below the minimum, and by max(1 − z × cv, 0) where it is above. That is its units moved z std to whichever side lowers the blend.
  - The blend reaches m under every such move exactly when the scaled shortfalls sum to at most 0. So it is still one linear row, exact for its m.
  - The relaxation's 0.5-point margin levels, and the least margin it reports, use the same shortfalls.
  - `guardrails.planned_margin` gives the least blend within the move, by Dinkelbach's iteration. Validation reports it, and the relaxation starts from it.
- **D4. When the budget margin alone puts a clearance target out of reach, the budget is planned at the expected promo cost.**
  - It is triggered when phase 1 (ADR 0040), run with the margin, leaves a shortfall and the budget quantile is above 0.5. Phase 1 then runs again with promo cost at its expected value, on the same half of the work budget.
    - If that reaches every target, the whole request is planned so, and the result's `safety_margin` says `budget_margin_waived` with a budget quantile of 0.5.
    - Otherwise the request is infeasible whatever the margin, and it is planned with the margin: its relaxation raises the budget to the plan's P90 promo cost, so accepting it gives a feasible request.
  - The re-run costs one extra phase-1 solve, only in that case. The main solve keeps at least half of its work budget, as before.
  - On the gate's requests it is `clear-dishwash-offseason`: its targets need the whole budget at expected cost, and its true spend was ₹1.43 lakh of ₹1.5 lakh.
  - We rejected declaring such a request infeasible (a scenario and a recording change) and never applying the margin with clearance targets.
- **D5. `validate_plan` checks the plan at the margin it was planned with.**
  - `LineFacts` gains `units_std` and `promo_cost_std`.
  - `PlanFacts` gains `safety`, the margin the optimiser applied, including the waived budget quantile.
  - The budget and regional caps are checked on P90 promo cost, stock on the buffered units, and the minimum margin and margin floor on `planned_margin`.
  - The defaults check expected values and P90 units, so plan facts stored before this ADR validate as before.
  - Every plan the solver accepts passes `validate_plan` (ADR 0012), and the eval's constraint satisfaction checks exactly what the optimiser enforced. A hypothesis property checks this over random options with spread.
- **D6. Three settings, in `SolverSettings`:**
  - `OPTIMIZER_BUDGET_QUANTILE=0.9` (0.5 to 0.99);
  - `OPTIMIZER_STOCK_BUFFER_SIGMAS=2` (at least 1.2816);
  - `OPTIMIZER_MARGIN_QUANTILE=0.1` (0.01 to 0.5).

  0.5, 1.2816 and 0.5 plan as before.
  - They are part of `RECORDED_SETTINGS`, since they decide the plan the Critic and the Explainer see (ADR 0054).
  - `.env.example` and the README list them.
  - `best_plan` and #157's default plan use the same solver settings, so the benchmarks keep the same margin.
  - We rejected fields on `CompanyPolicy`, which are not recorded and have no environment variable.
- **D7. What the user and the LLM see:**
  - `OptimisationResult.safety_margin` is a `PlanSafetyMargin`: the three quantiles, the `planned_promo_cost` the budget counted, and `budget_margin_waived`.
  - The `run_optimizer` output adds `planned_promo_cost` and `safety_margin`. The tool's description is unchanged, and output schemas do not reach the LLM.
  - `PlanRevision.safety_margin` keeps it. Migration 0015 adds the nullable JSONB column `plan_revisions.safety_margin`, so revisions from before read back with none.
  - The constraint checklist's rows read "Promo cost at its P90, ₹…, within the marketing budget", "expected units plus 2 standard deviations" and "Blended margin with units at their P10". A waived margin reads "Planned at the expected promo cost, without a safety margin: the clearance targets need the whole budget."
  - The Explainer's plan data gains `safety_margin`. Its template summary says what the budget counted, or that the margin was waived.
  - `make api-types` regenerates the frontend types.
- **D8. The oracle breach rate's target is at most 15%** of scored plans, judged pass or fail in the report (`at_most`).
  - Offline, the default plans reach 4/26–27, about 15%. The live planner adds variance, so the target is tight on purpose.
  - We rejected 20% and 10%. 10% needs k = 2.5, at −9% profit and a regret of 11.7%.
- **D9. The price is accepted:** the median default-plan regret moves from 7.8% to about 10.3% against a best plan with the same margin, just over SPEC's 10%, and expected profit falls about 5% on these requests.
  - #170 (shrinking the objective for estimation uncertainty) addresses model error separately.
- **D10. Sequencing.** This lands before the full 32-scenario re-record that follows #157, so one re-record covers both.

## What this amends

- **ADR 0005:** "The marketing budget caps total expected promo cost; P90 spend is reported, not constrained." The budget now counts each line's promo cost at the budget quantile, P90 by default.
- **ADR 0012:**
  - Its rejection of constraining spend and margin at P90 is reversed: the breach rate showed that expected-value planning at binding limits breaks them about half the time.
  - The oracle breach rate now has a target of at most 15%.
  - Constraint satisfaction stays on plan-time values: `validate_plan` checks them at the plan's safety margin.
- **ADR 0004 and SPEC §9.4:** P90 units still fit available stock. Expected units plus the stock buffer must fit too.
- **ADR 0036 and ADR 0040:** the budget, regional-cap and margin rows use the margin's coefficients. The eligible options also keep the stock buffer.
- **ADR 0044:** a relaxed budget or cap is what the plan spends at the budget quantile. A relaxed minimum margin is the least blend at the margin quantile.
- **ADR 0063:** the best plan, and #157's default plan, plan with the same safety margin.
- **SPEC §9.4 and §12.2** are updated to match.

## Consequences

- **New public names:**
  - domain: `SafetyMargin`, `PlanSafetyMargin` and `P90_Z`, moved from `optimizer.options` and still exported there;
  - guardrails: `budget_z`, `margin_z`, `promo_cost_std`, `planned_promo_cost`, `stock_units`, `margin_shortfall`, `planned_margin`, `units_cv` and `format_percentile`;
  - `SolverSettings.budget_quantile`, `stock_buffer_sigmas`, `margin_quantile` and `safety_margin`;
  - `LineFacts.units_std` and `promo_cost_std`, and `PlanFacts.safety`;
  - `OptimisationResult.safety_margin`, `PlanRevision.safety_margin`, and `RunOptimizerOutput.planned_promo_cost` and `safety_margin`;
  - `evals.metrics.ORACLE_BREACH_TARGET`.
- `plan_facts(options, rows, facts, safety)` takes the result's margin.
- **Solve time.** The margin changes coefficients only: no new variable or row, and on the gate's requests no slower solve. With clearance targets that the budget margin puts out of reach, one extra phase-1 solve runs.
- **LLM requests:**
  - The prompts and tool descriptions are unchanged.
  - The margin changes 27 of the gate's 28 plans. So from the first `run_optimizer` result on, the planner's requests miss their cassettes, and so do the Critic's and the Explainer's.
  - The three new recorded settings mean every app session's manifest reports a settings mismatch until `make record-cassettes` runs.
  - The PR lists the exact misses of an offline `--check` replay. The main session records the app sessions and smoke scenarios for this PR. The full 32-scenario re-record after #157 covers the rest.
