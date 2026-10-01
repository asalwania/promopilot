# Nine-blocker claim: F3 × D2

PromoPilot claims **F3 × D2** on the hackathon's 3×3 grid (SPEC §1.1, §2.1):

- **F3: all 9 features** of Problem 3, two above F3's threshold of 7, plus five supporting features (observability, trainability, fault tolerance, human oversight, explainability).
- **D2: structured tables plus a free-text brief as input, with reliability measured, not asserted.** Every final plan revision is scored against the hidden ground truth of a synthetic world that only the eval harness can read (ADR 0003, ADR 0010).
- **Not D3.** Multimodal input (flyer images, PDFs) is out of scope.

The claim rule, the evidence format and the source of every number are recorded in [ADR 0089](adr/0089-nine-blocker-claim-and-evidence-rules.md); how the evidence is cited, and checked, is [ADR 0091](adr/0091-the-matrix-cites-files-and-symbols-and-a-test-resolves-them.md). Vocabulary follows [CONTEXT.md](../CONTEXT.md); how the system is built is in the architecture document. <!-- LATE: link the architecture document (docs/architecture.md) once #75 (PR #183) merges -->

<!-- LATE: the numbers below are copied from backend/evals/published/latest.md, run 2026-09-30T14:54:13Z. Four things move them, and each is marked "LATE:" in place (search this file for "LATE:"): (1) the re-record after #187 (PR #187, Explainer totals) republishes the report, which moves grounding, session time and session cost and may move the rest, so re-copy every number and the timestamp if it does; (2) the `make eval RUNS=5 SMOKE=1` consistency run, which is not measured yet; (3) the verdict, which applies ADR 0089 D3 to the final numbers; (4) the re-check of the demo moments against the re-recorded sessions. -->

## Headline numbers

All numbers below come from one report: `backend/evals/published/latest.json`, generated 2026-09-30T14:54:13Z (run `20260930T145413Z`) with the `openai (recording)` provider on the seed-42 world, 33 scenarios, 1 run each, published in commit `de5d749` (#186). Consistency comes from a supplementary live run (see [Consistency](#consistency)). <!-- LATE: if the #187 re-record republishes latest.*, update this timestamp, provider and commit -->

| | Result | Target |
|---|---|---|
| Plans beating the rule-based baseline | 100.0% (30 of 30 scored runs) | ≥ 90% of scenarios |
| Final plans passing every hard constraint | 100.0% (30 of 30; 3 revisions are declared `INFEASIBLE` and counted apart) | 100% |
| Infeasible requests declared, with a relaxation | 100.0% (2 of 2) | 100% |
| Vague or conflicting briefs that ask or flag | 100.0% (3 of 3) | 100% |
| Explanations passing numeric grounding | 97.4% (38 of 39) **miss** <!-- LATE: grounding moves with the #187 re-record (PR #187 fixes the one ungrounded answer's cause) --> | ≥ 98% |
| §12.2 targeted metrics met | 10 of 13 pass; 2 miss (grounding, regret); consistency not yet measured <!-- LATE: n of 13 after the #187 re-record (grounding) and the RUNS=5 consistency run --> | most, per ADR 0089 D3 |

**Verdict:** D2 holds, on the strength of ADR 0089 D3: ten of the 13 targeted metrics pass, constraint satisfaction, clarification and infeasibility handling pass outright, and the two misses are listed in [Where we fall short](#where-we-fall-short) with their causes (grounding by one answer in 39, regret at 12.3% against 10%). <!-- LATE: re-apply ADR 0089 D3 after the #187 re-record and the RUNS=5 consistency run; "D2 holds" stands unless grounding, constraint satisfaction, clarification or infeasibility handling fail by more than a narrow, explained margin or fewer than seven metrics pass -->

## Justification

### F3: nine features and five supporting ones

Each of F-01…F-09 is built, tested and visible in the product. The [evidence matrix](#evidence-matrix) traces each one to its code, its tests, the moment it shows in the demo and the eval metric that measures it. Seven would be enough for F3; the other two are a buffer against a feature a judge does not accept.

The supporting features count toward the F axis (SPEC §1.1):

- **SF-01 Observability:** a live trace timeline over SSE, structured JSON logs with request and session ids, and token and cost counters per session.
- **SF-02 Trainability:** `POST /api/models/retrain` and `make train` fit and register new model versions with their metrics.
- **SF-03 Fault tolerance:** retries with backoff, a fallback LLM provider, deterministic fallbacks when the LLM is down, replay mode and checkpointed graph state.
- **SF-04 Human oversight:** nothing is final until a person approves it; rejections keep their reason; an audit trail lists every decision.
- **SF-05 Explainability:** every plan line has a rationale, and every number in it is checked against tool outputs.

### D2: structured input, demonstrable reliability

- **Input.** Structured tables (sales, inventory, competitor prices, holidays, margins, segments) plus a planning brief in free text. The brief is data, never instructions (ADR 0079). The Context agent reads it into a planning request, and every field records its source and confidence (AG-01).
- **Reliability is measured against ground truth.** The data generator hides the true demand function, elasticities and product relations (ADR 0003). The eval harness scores each final plan revision with the oracle on true demand and compares it with a rule-based baseline and with the best plan our optimiser finds on the true parameters (ADR 0063). The suite has 33 scenarios across SPEC §12.1's nine groups (ADR 0065).
- **The agent never computes numbers.** Every number comes from a deterministic tool (ADR 0002), an architecture test keeps business arithmetic out of the agents package, and recorded sessions are checked for grounding.

### Why not D3

D3 needs highly heterogeneous multimodal input. PromoPilot reads tables and text only; flyer images and PDFs are on the roadmap.

### The claim rule

We keep D2 when most of the 13 targeted §12.2 metrics pass **and** constraint satisfaction, clarification behaviour, infeasibility handling and grounding each pass or miss only narrowly with a stated cause. Every miss is listed in [Where we fall short](#where-we-fall-short). Otherwise the claim drops to D1, here and in the deck (ADR 0089 D3).

## Evidence matrix

SPEC §16, filled in. Code is cited by file and function or class (ADR 0091), not by line number: lines move with every merge, names are checked by a test. Code paths are under `backend/src/promopilot/`; pytest ids are under `backend/`; frontend paths are from the repository root. Each row's full evidence is in its subsection below.

| Claim | Evidence in code | Test(s) | Demo moment | Eval metric |
|---|---|---|---|---|
| [F-01 Select products](#f-01-select-which-products-to-promote) | `optimizer/solver.py` `solve`, `optimizer/options.py` `generate_options` | hard-constraint property tests, not-selected reasons | plan table + "Not selected" list | plan quality, regret |
| [F-02 Mechanism](#f-02-determine-the-promotion-mechanism) | `mechanisms/compare.py` `compare`, `models/response.py` `PromoResponse` | comparator tests | mechanism drawer | plan quality |
| [F-03 Discount + strategy](#f-03-optimise-the-discount-and-customise-other-strategies) | `optimizer/options.py` `generate_options`, `models/demand.py` `DemandModel`, `models/response.py` `PromoResponse` | monotonicity property tests | depth / duration / segment columns, uplift by segment | elasticity recovery |
| [F-04 Cannibalisation](#f-04-understand-cannibalisation) | `models/relations.py` `fit` and `line_effects`, strong-substitute rule in `optimizer/solver.py` | substitute detection and cross-effect tests | cannibalisation findings and callout | substitute P/R, heavy-cannibalisation scenarios |
| [F-05 Relationships](#f-05-understand-product-relationships) | `models/relations.py` `fit` and `line_effects`, `mechanisms/compare.py` `compare` | complement and halo tests | `BUNDLE` row of the mechanism drawer, halo callout | complement P/R |
| [F-06 Inventory](#f-06-consider-inventory-constraints) | optimiser stock and clearance constraints, `guardrails/validation.py` `validate_plan`, `guardrails/safety.py` | stock and clearance constraint tests | stock-out risk column, clearance met | constraint satisfaction, oracle breach rate |
| [F-07 Geography](#f-07-geographically-customise-promotions) | one joint solve over region-level plan lines (`optimizer/solver.py` `solve`) | region tests | region tabs side by side | regional holiday scenarios |
| [F-08 Competitor](#f-08-competitor-awareness) | `competitors/gaps.py` `competitor_gaps`, price-match options, KVI tolerance | competitor tests | competitor panel | competitor price-war scenarios |
| [F-09 Simulation](#f-09-simulate-the-promotion-before-launching) | `simulator/simulate.py` `simulate` | determinism + invariant tests | P10–P90 chart | — |
| [D2 reliability](#d2-reliability) | `evals/runner.py` `run`, `evals/oracle.py` `Oracle` | eval runner tests | `/evals` dashboard | all §12.2 metrics |
| [Supporting features](#supporting-features) | trace, logs, retrain, fallback, approval, grounding | agent + API tests | trace timeline, approve step | grounding, consistency |

### F-01 Select which products to promote

- **Code.**
  - `optimizer/solver.py` `solve`: a CP-SAT model that picks at most one promo option per SKU and region (ADR 0036).
  - `optimizer/options.py` `generate_options`: the candidate set, pruned of options whose P90 units exceed available stock (ADR 0035).
  - Each plan line says why it was chosen, and the top five not-selected options say why not (`domain/selection.py` `WhyChosen` and `NotSelectedOption`, ADR 0067).
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_every_returned_plan_satisfies_every_hard_constraint` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_only_lines_with_a_positive_value_are_selected`
  - `tests/unit/optimizer/test_solve_reports.py::test_every_plan_line_says_why_and_every_listed_option_says_why_not` (hypothesis)
  - `tests/unit/optimizer/test_solve_reports.py::test_at_most_five_are_listed_best_value_first`
  - `frontend/tests/unit/not-selected-list.test.tsx`, `frontend/tests/unit/plan-table.test.tsx`
- **Demo moment.** The "Diwali demo" example brief: the plan table per region and the "Not selected" list (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.**
  - Plan quality: 100.0% (30 of 30 scored runs beat the rule-based baseline; target ≥ 90%).
  - Regret, median: 12.3% against a 10% target, a **miss** (12 of 29 runs within 10%). Regret by cause: model error is the largest part in 16 of the 17 runs above 10%, the planner's choices in 1, and timeouts in none; one run's best plan is infeasible and is not counted (ADR 0078; see [Where we fall short](#where-we-fall-short)).

### F-02 Determine the promotion mechanism

- **Code.**
  - `mechanisms/compare.py` `compare`: for each plan line, the best option of each mechanism (`PCT_OFF`, `BOGO`, `BUNDLE`, `FIXED_PRICE`) with its expected profit, units and margin (ADR 0041). The planner calls it through `agents/tools/compare_mechanisms.py`.
  - `models/response.py` `PromoResponse`: mechanism effects are fitted from promo history, not hard-coded (ADR 0024).
  - `optimizer/options.py` `generate_options`: a `BUNDLE` is generated only with a detected complement.
- **Tests.**
  - `tests/unit/mechanisms/test_compare.py::test_each_mechanism_shows_its_best_option_by_value_with_that_options_numbers`
  - `tests/unit/mechanisms/test_compare.py::test_bundle_is_compared_only_for_a_sku_with_a_complement`
  - `tests/unit/mechanisms/test_compare.py::test_the_comparison_is_deterministic`
  - `tests/unit/models/test_promo_response.py::test_mechanism_effects_are_estimated_from_promo_history`
  - `tests/unit/optimizer/test_generate_options.py::test_a_bundle_appears_only_with_a_detected_complement_even_outside_the_scope`
  - `frontend/tests/unit/mechanism-drawer.test.tsx`
- **Demo moment.** "Compare mechanisms for …" on a plan line opens the mechanism drawer with the chosen mechanism marked (`frontend/tests/e2e/brief-to-plan.spec.ts`). In the recorded demo session the chosen mechanisms are `PCT_OFF` and `FIXED_PRICE`, with `BOGO` and `BUNDLE` compared. <!-- LATE: re-check against the sessions re-recorded for #187 -->
- **Eval metric.** Plan quality: 100.0% (30 of 30). There is no mechanism-specific metric; the mechanism is one of the decisions the oracle scores.

### F-03 Optimise the discount and customise other strategies

- **Code.**
  - `optimizer/options.py` `generate_options`: options over depth (5–50%), duration (1–4 weeks), target segment (one segment or All customers, ADR 0006) and start week inside the promo window (ADR 0005, ADR 0035).
  - `optimizer/solver.py` `solve`: the objective chooses among them under the budget, margin and caps.
  - `models/demand.py` `DemandModel` and `models/response.py` `PromoResponse`: the baseline forecast and the promo response with own-price elasticities per segment (ADR 0023, ADR 0024).
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_lowering_the_budget_never_deepens_the_average_discount` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_raising_the_minimum_margin_never_deepens_the_average_discount` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_tightening_the_budget_never_increases_the_objective` (hypothesis)
  - `tests/unit/optimizer/test_generate_options.py::test_every_option_starts_and_ends_inside_the_promo_window`
  - `tests/unit/optimizer/test_generate_options.py::test_both_segment_targeted_and_all_customers_options_are_present`
  - `tests/unit/models/test_promo_response.py::test_a_segment_exclusive_offer_changes_only_that_segment`
  - `tests/unit/models/test_promo_response.py::test_recovered_elasticities_are_close_to_the_true_ones`
- **Demo moment.** The depth, duration and segment columns of each plan line, and the "Uplift by segment" table in its details (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.** Elasticity recovery, median absolute % error: 8.1% (679 of 800 SKU × segment elasticities within 20%; target ≤ 20%).

### F-04 Understand cannibalisation

- **Code.**
  - `models/relations.py` `fit`: substitutes from cross-price effects within each subcategory, kept at a Benjamini–Hochberg q below 0.05 and a minimum effect size (ADR 0013, ADR 0029).
  - `models/relations.py` `line_effects` and `pairwise_cannibalisation`: plan value is net of cannibalised sister-SKU profit, per plan line and per pair (ADR 0033).
  - `optimizer/solver.py` `solve` and `guardrails/validation.py` `validate_plan`: strong substitutes are never promoted together in the same region, week and segment (ADR 0075).
- **Tests.**
  - `tests/unit/models/test_relations.py::test_a_substitute_needs_a_bh_q_below_005_and_the_minimum_effect_size`
  - `tests/unit/models/test_relations.py::test_substitutes_are_detected_with_good_precision_and_recall`
  - `tests/unit/models/test_cross_effects.py::test_a_line_cannibalises_every_substitute_in_its_region_in_scope_or_not`
  - `tests/unit/optimizer/test_solve_substitutes.py::test_two_strong_substitutes_are_never_promoted_together`
  - `tests/unit/guardrails/test_validate_plan.py::test_two_strong_substitutes_promoted_together_are_flagged`
  - `frontend/tests/unit/cross-effect-callouts.test.tsx`
- **Demo moment.** The cannibalisation callout on a plan line: "Promoting A reduces B's units by N%" (`frontend/tests/unit/cross-effect-callouts.test.tsx`). In the recorded `regional` and `e2e` sessions the Critic raises a heavy-cannibalisation finding, for example "SKU0035 in North … the cannibalisation of its substitutes ₹935 is 266.3% of its incremental profit ₹351", shown as a Critic finding in the trace timeline. The callout itself is not asserted in a recorded session's end-to-end test (ADR 0089 D9). <!-- LATE: re-check the finding against the sessions re-recorded for #187 -->
- **Eval metric.**
  - Substitute detection: precision 86.7% (91 of 105; target ≥ 80%), recall 100.0% (91 of 91; target ≥ 70%).
  - Heavy-cannibalisation scenarios passing `no_strong_substitutes_together`: 3 of 3.

### F-05 Understand product relationships

- **Code.**
  - `models/relations.py` `fit`: complements from basket co-occurrence (lift above a threshold, with minimum support) and negative cross-price effects (ADR 0029).
  - `models/relations.py` `line_effects`: halo on complements is added to plan value and shown per plan line (ADR 0033).
  - `mechanisms/compare.py` `compare`: a bundle suggestion lists the pair, its lift and its expected incremental profit.
- **Tests.**
  - `tests/unit/models/test_relations.py::test_complements_need_lift_above_the_threshold_and_minimum_support`
  - `tests/unit/models/test_relations.py::test_complements_are_detected_with_good_precision_and_recall`
  - `tests/unit/models/test_cross_effects.py::test_a_line_lifts_a_complement_in_its_region_and_counts_it_as_halo`
  - `tests/unit/mechanisms/test_compare.py::test_a_bundle_suggestion_lists_the_pair_its_lift_and_its_incremental_profit`
  - `frontend/tests/unit/cross-effect-callouts.test.tsx`
- **Demo moment.** The `BUNDLE` row of the mechanism drawer, compared on plan lines of the recorded demo, `regional` and `e2e` sessions, and the halo callout on a plan line. None of the five recorded demo sessions chooses a `BUNDLE` line, so a chosen bundle and a halo callout are shown by `test_a_bundle_suggestion_lists_the_pair_its_lift_and_its_incremental_profit`, `frontend/tests/unit/cross-effect-callouts.test.tsx` and the complement recovery below; the eval recording does hold plan lines with a bundle partner (ADR 0089 D9). <!-- LATE: re-check against the sessions and eval cassettes re-recorded for #187 -->
- **Eval metric.** Complement detection: precision 100.0% (39 of 39; target ≥ 80%), recall 97.5% (39 of 40; target ≥ 70%).

### F-06 Consider inventory constraints

- **Code.**
  - `optimizer/options.py` `generate_options`: options whose P90 units exceed available stock are pruned before the solve.
  - `optimizer/solver.py` `solve`: clearance targets for overstocked SKUs the brief names; an unreachable target gives the closest plan with its clearance shortfall, and the revision is `INFEASIBLE` (ADR 0040, ADR 0074).
  - `guardrails/validation.py` `validate_plan`: every hard constraint checked on plan-time values (ADR 0012).
  - Plans keep a safety margin: the budget at P90 promo cost, stock with a 2σ buffer, the margin at P10 units (ADR 0080), in `guardrails/safety.py` `planned_promo_cost`, `stock_units` and `planned_margin`, configured by `domain/safety.py` `SafetyMargin` (#159).
  - `simulator/simulate.py` `simulate`: stock-out probability per plan line.
- **Tests.**
  - `tests/unit/optimizer/test_generate_options.py::test_options_whose_p90_units_exceed_available_stock_are_pruned`
  - `tests/unit/guardrails/test_validate_plan.py::test_p90_units_above_available_stock_are_flagged_per_line`
  - `tests/unit/optimizer/test_solve_constraints.py::test_a_clearance_target_is_met_even_by_a_line_that_loses_money`
  - `tests/unit/optimizer/test_solve_constraints.py::test_an_unreachable_clearance_target_gives_the_closest_plan_and_reports_the_shortfall`
  - `tests/unit/optimizer/test_solve_safety_margin.py::test_expected_units_must_leave_the_stock_buffer`
  - `tests/unit/optimizer/test_solve_safety_margin.py::test_any_plan_keeps_its_p90_budget_stock_buffer_and_p10_margin` (hypothesis)
  - `tests/unit/guardrails/test_safety_margin.py::test_stock_holds_the_expected_units_plus_the_buffer`
  - `tests/unit/simulator/test_simulate.py::test_stock_out_probability_is_one_with_no_stock`
  - `frontend/tests/unit/constraint-checklist.test.tsx`
- **Demo moment.** The "Diwali demo" brief clears at least 60% of its overstocked 400g namkeen packs. Its three recorded revisions (the brief, "Budget cut to ₹6 lakh", "Drop West") are all `OPTIMAL` with no clearance shortfall, and the constraint checklist's Clearance row reads Pass (`frontend/tests/e2e/amend.spec.ts`, ADR 0086). The plan table's stock-out risk column shows each line's risk (`frontend/tests/unit/plan-table.test.tsx`). The `infeasible` recorded session shows the opposite case: a 95% clearance on a ₹10k budget is declared infeasible with its shortfall (`frontend/tests/e2e/infeasible.spec.ts`).
- **Eval metric.**
  - Constraint satisfaction: 100.0% (30 of 30; target 100%).
  - Oracle breach rate: 13.3% (4 of 30; target ≤ 15%, ADR 0080).
  - Overstock-clearance scenarios passing: 4 of 4.

### F-07 Geographically customise promotions

- **Code.**
  - One joint solve over region-level plan lines with pooled regional stock (ADR 0004): each region gets its own lines from its own demand, stock, segment mix, holidays and competitor prices, under one shared budget (`optimizer/solver.py` `solve`).
  - Regional budget caps (ADR 0040) in `optimizer/solver.py` `solve`.
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_per_region_plans_follow_regional_holidays`
  - `tests/unit/optimizer/test_solve_constraints.py::test_a_regional_budget_cap_limits_the_promo_cost_spent_in_its_region`
  - `tests/unit/models/test_cross_effects.py::test_a_line_has_no_effect_in_another_region`
  - `frontend/tests/unit/region-plan-tabs.test.tsx`
- **Demo moment.**
  - Region tabs and "Compare regions" side by side (`frontend/tests/e2e/brief-to-plan.spec.ts`); "Christmas, every region" plans all four regions with a ₹1 lakh cap on South (the recorded `regional` session).
  - Regional holidays are not in the demo recordings. They are shown by the scenarios `pongal-2026-south`, `durga-puja-2025-east` and `lohri-2026-north` and by `test_per_region_plans_follow_regional_holidays` (ADR 0089 D9).
- **Eval metric.** Regional-holiday scenarios passing: 3 of 3.

### F-08 Competitor awareness

- **Code.**
  - `competitors/gaps.py` `competitor_gaps`: competitor price index and gap per SKU and region, and the undercut flag for KVIs past the company-policy threshold (ADR 0031).
  - `models/response.py` `PromoResponse`: the competitor price index is a demand-model input.
  - `optimizer/options.py` `generate_options`: an undercut KVI gets a price-match option in its region.
  - The optional KVI tolerance keeps KVI promo prices near the competitor's (`optimizer/solver.py` `solve`, `guardrails/validation.py` `validate_plan`).
  - The planner states each undercut and its response in a planner note, grounded against the gaps.
- **Tests.**
  - `tests/unit/competitors/test_competitor_gaps.py::test_with_the_default_threshold_a_4_9_pct_gap_is_not_undercut_and_5_1_pct_is`
  - `tests/unit/competitors/test_competitor_gaps.py::test_a_partial_response_says_how_many_of_the_undercut_skus_it_matches`
  - `tests/unit/models/test_promo_response.py::test_a_competitor_undercut_lowers_predicted_units`
  - `tests/unit/optimizer/test_generate_options.py::test_an_undercut_kvi_gets_a_price_match_option_in_its_region`
  - `tests/unit/optimizer/test_solve_constraints.py::test_the_kvi_tolerance_keeps_kvi_promo_prices_near_the_competitor_when_enabled`
  - `tests/unit/agents/test_planner_agent.py::test_an_undercut_kvi_is_explained_with_its_gap_and_the_plans_response`
  - `frontend/tests/unit/competitor-panel.test.tsx`, `frontend/tests/unit/undercut-callout.test.tsx`
- **Demo moment.** The competitor panel on "Christmas, every region", which keeps KVIs within 3% of competitor prices; the planner notes name each undercut SKU, for example "Competitor is 13.9% cheaper on SKU0002 (Crunchy Namkeen 400g) in North (₹72.34 vs ₹84.00)" (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.** Competitor price-war scenarios passing: 4 of 4.

### F-09 Simulate the promotion before launching

- **Code.**
  - `simulator/simulate.py` `simulate`: vectorised Monte Carlo (1,000 seeded runs by default) over parameter uncertainty and demand noise, with an optional competitor-reaction scenario (ADR 0042, ADR 0045). It returns P10/P50/P90 of units, revenue, profit, margin and sell-through, and stock-out probability, per plan line and for the plan.
  - The planner calls it through `agents/tools/simulate_plan.py`; `POST /api/plans/{id}/simulate` re-simulates (ADR 0043).
- **Tests.**
  - `tests/unit/simulator/test_simulate.py::test_the_same_seed_gives_identical_results`
  - `tests/unit/simulator/test_simulate.py::test_p10_p50_p90_are_ordered_for_every_metric` (hypothesis)
  - `tests/unit/simulator/test_simulate.py::test_a_matched_discount_lowers_p50_units_on_an_undercut_sensitive_sku`
  - `tests/unit/simulator/test_simulation_speed.py::test_a_100_line_plan_simulates_1000_runs_within_the_budget`
  - `frontend/tests/unit/simulation-panel.test.tsx`
- **Demo moment.** The "Simulated gross profit by plan line" band chart, and Re-simulate with a competitor reaction (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.** — (SPEC §16). The simulator's accuracy is not scored against the oracle; its determinism, quantile order and speed are tested.

### D2 reliability

- **Code.** `evals/runner.py` `run` plays each scenario through the real agent graph; `evals/metrics.py` `constraint_satisfaction`, `evals/behaviour.py`, `evals/quality.py` and `evals/recovery.py` score it; `evals/oracle.py` `Oracle` judges plans on true demand; `evals/report.py` writes the JSON and Markdown report (ADR 0056, ADR 0062–0064). Scenarios are `backend/evals/scenarios/*.yaml`.
- **Tests.**
  - `tests/evals/test_runner.py::test_the_run_is_deterministic_for_a_seed`
  - `tests/evals/test_runner.py::test_every_scored_plan_is_compared_with_the_rule_based_baseline_and_the_best_plan`
  - `tests/evals/test_suite.py::test_the_suite_has_at_least_the_spec_count_in_every_group_and_30_in_all`
  - `tests/evals/test_quality.py::test_regret_is_the_median_over_scored_runs_against_at_most_10_percent`
  - `tests/evals/test_quality.py::test_with_one_run_per_scenario_consistency_is_not_scored`
  - `tests/architecture/test_ground_truth_boundary.py::test_only_datagen_and_evals_reference_the_ground_truth`
  - `frontend/tests/e2e/evals.spec.ts`
- **Demo moment.** The `/evals` dashboard: metric cards against targets, the regret chart and the per-scenario table.
- **Eval metric.** All of SPEC §12.2: see [Final eval numbers](#final-eval-numbers).

### Supporting features

| Feature | Code | Tests | Demo moment |
|---|---|---|---|
| SF-01 Observability | `agents/trace.py`, the SSE route in `api/sessions.py`, `logs.py`, `llm/usage.py` (ADR 0047, ADR 0085) | `tests/unit/agents/test_graph_trace.py::test_a_planning_run_traces_every_node_in_order_up_to_the_approval_pause`, `tests/integration/test_session_events_api.py::test_the_stream_sends_every_event_in_order_then_ends_once_approved`, `tests/integration/test_session_logs_api.py::test_every_line_of_a_session_request_carries_the_request_and_session_ids`, `tests/unit/llm/test_usage.py::test_totals_add_tokens_and_price_each_call_by_its_model` | the trace timeline and the usage meter |
| SF-02 Trainability | `models/training.py` `train_models`, `models/registry.py` `ModelRegistry`, `api/models.py` (ADR 0026) | `tests/integration/test_models_api.py::test_retrain_registers_a_new_version_that_becomes_the_latest_and_live` | the `/models` page's retrain button |
| SF-03 Fault tolerance | `llm/resilience.py` `RetryingProvider` and `FallbackProvider`, `agents/fallback.py`, `agents/checkpoints.py`, `llm/replay.py` `ReplayProvider` (ADR 0027, ADR 0053) | `tests/unit/llm/test_resilience.py::test_after_the_primary_exhausts_its_retries_the_secondary_answers`, `tests/unit/agents/test_graph.py::test_with_the_llm_down_at_context_the_demo_brief_still_reaches_a_plan`, `tests/integration/test_sessions_api.py::test_approval_after_a_restart_resumes_the_graph_from_its_checkpoint` | `make demo` replays every example brief with no API key |
| SF-04 Human oversight | the approval interrupt in `agents/graph.py` `build_graph`; approve and reject in `api/sessions.py` (ADR 0046) | `tests/unit/agents/test_graph.py::test_rejecting_records_the_reason_and_waits_at_approval_again`, `frontend/tests/e2e/approve.spec.ts`, `frontend/tests/e2e/reject.spec.ts` | approve after a confirm, reject with a reason, the audit trail |
| SF-05 Explainability | `guardrails/grounding.py` `check_numeric_grounding`, `agents/explainer.py` `explain_plan` (ADR 0028, ADR 0050) | `tests/unit/agents/test_grounded_explainer.py::test_a_second_ungrounded_answer_falls_back_to_the_template`, `tests/architecture/test_recorded_sessions_are_grounded.py::test_every_number_in_a_recorded_explanation_or_critique_is_in_its_tool_data` | each plan line's rationale; every number's source tooltip |

Eval metrics: grounding 97.4% (38 of 39; target ≥ 98%, a miss) <!-- LATE: grounding after the #187 re-record -->; consistency not yet measured (target ≥ 0.9) <!-- LATE: mean Jaccard from the RUNS=5 report -->.

## Agentic capabilities

SPEC §5 AG-01…AG-06, judged under evaluation criterion 5 (ADR 0089 D6).

| Capability | Code | Tests | Demo moment | Eval metric |
|---|---|---|---|---|
| AG-01 Parameter extraction | `agents/context.py` `read_brief`, `agents/resolution.py`, `agents/assumptions.py` (ADR 0048) | `tests/unit/agents/test_context_agent.py::test_a_brief_stating_every_critical_field_becomes_a_request_with_its_assumptions` | the assumptions panel with source and confidence | extraction accuracy 100.0% (152 of 152 fields; ≥ 95%) |
| AG-02 Clarification | the Clarify interrupt in `agents/graph.py` `build_graph` | `tests/unit/agents/test_graph.py::test_a_missing_budget_routes_to_clarify_and_the_answer_resumes_to_the_planner`, `frontend/tests/e2e/clarify.spec.ts` | "No budget: the agent asks" | clarification behaviour 100.0% (3 of 3; 100%) |
| AG-03 Tool use | `agents/planner_agent.py` `plan_with_tools`, `agents/tools/registry.py` (ADR 0025, ADR 0049) | `tests/unit/agents/test_planner_agent.py::test_scripted_tool_calls_on_the_small_world_produce_the_optimised_plan_each_traced`, `tests/unit/agents/test_tool_registry.py::test_arguments_that_break_the_input_schema_give_a_typed_error` | tool calls with arguments and results in the trace timeline | — |
| AG-04 Self-correction | `agents/critic.py` `review_attempt` and `best_attempt`, `guardrails/risks.py` `review_risks` (ADR 0051, ADR 0059, ADR 0084) | `tests/unit/agents/test_critic_loop.py::test_violations_loop_to_the_planner_at_most_3_times_then_go_to_the_explainer`, `tests/unit/agents/test_critic_loop.py::test_a_finding_goes_away_when_the_next_attempt_caps_its_skus_depth` | Critic findings and decisions in the trace | open issues per final plan: median 1, 41 in all over 33 plans (report) |
| AG-05 Dynamic re-planning | `agents/amendments.py`, `guardrails/diff.py` `diff_revisions` (ADR 0052) | `tests/unit/agents/test_amend.py::test_cutting_the_budget_plans_a_new_revision_within_it_with_a_diff`, `frontend/tests/e2e/amend.spec.ts` | "Budget cut to ₹6 lakh", then "Drop West": the revision diff | mid-plan amendment scenarios 4 of 4 |
| AG-06 Infeasibility handling | `optimizer/relaxation.py` `relaxed_request`, `agents/tools/relax_constraints.py` (ADR 0044, ADR 0083) | `tests/unit/optimizer/test_solve_relaxation.py::test_infeasible_instances_are_reported_infeasible_with_a_relaxation` (hypothesis), `frontend/tests/e2e/infeasible.spec.ts` | the infeasibility panel: binding constraints, the smallest relaxation, accept and re-plan (the recorded `infeasible` session) | infeasibility handling 100.0% (2 of 2; 100%) |

## Final eval numbers

Copied from `backend/evals/published/latest.md`, generated 2026-09-30T14:54:13Z (`openai (recording)` provider, seed-42 world, 33 scenarios, 1 run each). <!-- LATE: re-copy the whole table if the #187 re-record republishes latest.* -->

| Metric | Value | Target | Result |
|---|---|---|---|
| Constraint satisfaction | 100.0% (30 of 30) | 100% | pass |
| Oracle breach rate | 13.3% (4 of 30) | ≤ 15% (ADR 0080) | pass |
| Extraction accuracy | 100.0% (152 of 152) | ≥ 95% | pass |
| Clarification behaviour | 100.0% (3 of 3) | 100% | pass |
| Infeasibility handling | 100.0% (2 of 2) | 100% | pass |
| Grounding | 97.4% (38 of 39) <!-- LATE: grounding after the #187 re-record --> | ≥ 98% | **miss** <!-- LATE: result after the #187 re-record --> |
| Elasticity recovery (median abs % error) | 8.1% (679 of 800) | ≤ 20% | pass |
| Substitute precision / recall | 86.7% (91 of 105) / 100.0% (91 of 91) | ≥ 0.8 / ≥ 0.7 | pass |
| Complement precision / recall | 100.0% (39 of 39) / 97.5% (39 of 40) | ≥ 0.8 / ≥ 0.7 | pass |
| Baseline WAPE (region × SKU, store × SKU, store × SKU × segment) | 13.5%, 25.1%, 43.5% | report (aim ≤ 25%) | — |
| Plan quality (beats the rule-based baseline) | 100.0% (30 of 30) | ≥ 90% | pass |
| Regret (median, against the best plan) | 12.3% (12 of 29 runs within 10%) | ≤ 10% | **miss** |
| Consistency (Jaccard across 5 runs) | not measured <!-- LATE: mean Jaccard from the RUNS=5 report --> | ≥ 0.9 | <!-- LATE: pass or miss --> pending |
| Open issues per final plan (median) | 1 (21 of 33 plans have at least one; 41 in all) | report | — |
| P50 session time | 68.3 s (slowest 297 s; LLM P50 36 s) <!-- LATE: session time after the #187 re-record --> | report (SPEC §6: under 60 s) | — |
| P50 session cost | ₹3.54 (448 LLM calls in all) <!-- LATE: session cost after the #187 re-record --> | report (SPEC §6: under ₹20) | — |

Scenarios passing by group (a scenario passes when its final plan meets its expected properties):

| Group | Passing |
|---|---|
| Standard festive plans | 6 of 6 |
| Tight budget | 4 of 4 |
| Overstock clearance | 4 of 4 |
| Competitor price war | 4 of 4 |
| Regional holidays | 3 of 3 |
| Heavy cannibalisation | 3 of 3 |
| Vague or conflicting briefs | 3 of 3 |
| Infeasible constraints | 2 of 2 |
| Mid-plan amendments | 4 of 4 |

A scenario passing its properties does not mean its plan was close to the best plan: see regret below.

### Consistency

Under replay a scenario's runs are identical by construction (ADR 0063), so consistency is measured by a supplementary live run: `make eval RUNS=5 SMOKE=1` (the five smoke scenarios, five runs each), generated <!-- LATE: generated_at of the consistency report --> _pending_ with the <!-- LATE: provider of the consistency report --> _pending_ provider. Mean Jaccard of selected SKUs: <!-- LATE: mean Jaccard from the RUNS=5 report --> _pending_ (target ≥ 0.9).

## Where we fall short

Every miss against a §12.2 target or a SPEC §6 requirement, with its cause (ADR 0089 D3, D8).

- **Regret: median 12.3% against ≤ 10% (a miss).** Twelve of 29 counted runs are within 10%; the best plan of one more run is infeasible and is not counted. Of the 17 runs above 10%, model error is the largest part in 16 and the planner's choices in 1 (`demo-budget-cut-drop-west`, 60.5% of its 69.5%); timeouts are never the largest part. Over all counted runs the median model-error part is 9.1% (₹150,918 in all) against 0.0% for the planner (₹67,913) and for timeouts. The cause is the optimiser's curse: the optimiser selects the options the fitted model overestimates (#170, ADR 0078). The tail is long: `price-war-staples-christmas-2025` shows 109.7% because its best plan earns only ₹1,575. We keep D2 on the strength of the other targets (ADR 0089 D3); the miss is not hidden.
- **Grounding: 97.4% (38 of 39) against ≥ 98% (a miss).** One Explainer answer, in `price-war-staples-christmas-2025`, fell back to the template after its regenerated answer was still ungrounded, and every other answer passed. The cause is an Explainer figure the plan data does not show, which the guard rejects because the LLM never computes numbers. PR #187 (#185) puts the plan totals the LLM tends to derive into the plan data and re-records the Explainer; only that re-record shows whether this scenario then passes. <!-- LATE: grounding after the #187 re-record; drop this entry if it reaches 98% -->
- **Consistency: not measured on this report.** Replay cannot vary a scenario's runs; the supplementary live run is pending. <!-- LATE: consistency result from the RUNS=5 report; add a miss entry here if it is below 0.9 -->
- **Baseline forecast WAPE** is 13.5% by region × SKU and 25.1% by store × SKU, at the aim of 25%, and 43.5% by store × SKU × segment, above it. SPEC §12.2 asks to report it with an aim, not to meet a target.
- **Latency: P50 session 68.3 s over the 33 scenarios, slowest 297 s, against SPEC §6's 60 s for a 2 regions × 2 categories plan.** The median covers scenarios larger than that benchmark and the amendment sessions' several rounds, and it counts recorded LLM calls the harness replayed from cassettes, so the LLM share (P50 36 s) is understated for a fully live run. The solver is the cause on the largest scopes (#166, #168 below). #113 cut `generate_options` on the demo brief from about 16.6 s to about 4.2 s on a loaded machine (ADR 0087). Cost per session, ₹3.54 at the median, is well within the ₹20 target. <!-- LATE: latency and cost after the #187 re-record -->

### Known gaps

Open follow-up issues, each a known gap and not a hidden one:

- **#166, CP-SAT wall time:** the 10 deterministic-second budget takes 52–105 s of wall time on the largest scopes, over the 60 s wall-clock net, so on big scopes the plan can depend on the machine.
- **#168, binding analysis:** its re-solves run one after another and cost about 30 s per attempt on the demo brief; running them concurrently on fixed deterministic shares is not done.
- **#170, optimiser's curse:** the objective is not shrunk for estimation uncertainty, which is the main cause of the regret miss.
- **#171, `/evals` dashboard:** it does not yet show regret by cause, though the Markdown and JSON reports do.
- **#174, clearance asks:** a clearance ask cannot name SKU ids, and the first ask wins over a later one in free text; accepted relaxations are unaffected (ADR 0083).
- **#181, Critic tolerance:** the 5% objective tolerance may discard a depth cap that would resolve a finding; it is not tuned against this re-record.

## Reproduce the numbers

- `make eval`: every scenario once on the seed-42 world, into `backend/evals/reports/` (`<timestamp>.json` and `.md`, plus `latest.*`). With no API key it replays the committed cassettes.
- `make eval RUNS=5 SMOKE=1`: the consistency run. It measures something only with a live LLM (`OPENAI_API_KEY`).
- `make eval-smoke`: what CI runs on every PR, five scenarios with no key.
- The `/evals` page shows the latest report; `make demo` serves the published one from `backend/evals/published/`.
- `uv run pytest tests/tools/test_nine_blocker_matrix.py` (from `backend/`): checks that every file, function, test and scenario this document cites exists.

See the README's [Evals](../README.md#evals) section for scenario format, metrics and options.
