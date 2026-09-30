# Nine-blocker claim: F3 × D2

PromoPilot claims **F3 × D2** on the hackathon's 3×3 grid (SPEC §1.1, §2.1):

- **F3: all 9 features** of Problem 3, two above F3's threshold of 7, plus five supporting features (observability, trainability, fault tolerance, human oversight, explainability).
- **D2: structured tables plus a free-text brief as input, with reliability measured, not asserted.** Every final plan revision is scored against the hidden ground truth of a synthetic world that only the eval harness can read (ADR 0003, ADR 0010).
- **Not D3.** Multimodal input (flyer images, PDFs) is out of scope.

The claim rule, the evidence format and the source of every number are recorded in [ADR 0089](adr/0089-nine-blocker-claim-and-evidence-rules.md). Vocabulary follows [CONTEXT.md](../CONTEXT.md); how the system is built is in [docs/architecture.md](architecture.md).

<!-- LATE: every number, count and timestamp in this document is filled in from the main session's clean live recording of all 33 scenarios, published to backend/evals/published/ after #159, #141 and #142 merge (ADR 0089 D2). Search this file for "LATE:" to find each one. -->

## Headline numbers

All numbers below come from one report: `backend/evals/published/latest.json`, generated <!-- LATE: generated_at --> **_pending_** with the <!-- LATE: provider --> **_pending_** provider on the seed-42 world, <!-- LATE: scenario count, expected 33 --> **_pending_** scenarios, committed in <!-- LATE: commit sha --> **_pending_**. Consistency comes from a supplementary live run (see [Consistency](#consistency)).

| | Result | Target |
|---|---|---|
| Plans beating the rule-based baseline | <!-- LATE --> _pending_ | ≥ 90% of scenarios |
| Final plans passing every hard constraint | <!-- LATE --> _pending_ | 100% |
| Infeasible requests declared, with a relaxation | <!-- LATE --> _pending_ | 100% |
| Vague or conflicting briefs that ask or flag | <!-- LATE --> _pending_ | 100% |
| Explanations passing numeric grounding | <!-- LATE --> _pending_ | ≥ 98% |
| §12.2 targeted metrics met | <!-- LATE: n of 13 --> _pending_ | most, per ADR 0089 D3 |

**Verdict:** <!-- LATE: "D2 holds" or "downgraded to D1", applying ADR 0089 D3 to the final numbers --> _pending_.

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
- **Reliability is measured against ground truth.** The data generator hides the true demand function, elasticities and product relations (ADR 0003). The eval harness scores each final plan revision with the oracle on true demand and compares it with a rule-based baseline and with the best plan our optimiser finds on the true parameters (ADR 0063). The suite has <!-- LATE: 33 --> _pending_ scenarios across SPEC §12.1's nine groups (ADR 0065).
- **The agent never computes numbers.** Every number comes from a deterministic tool (ADR 0002), an architecture test keeps business arithmetic out of the agents package, and recorded sessions are checked for grounding.

### Why not D3

D3 needs highly heterogeneous multimodal input. PromoPilot reads tables and text only; flyer images and PDFs are on the roadmap.

### The claim rule

We keep D2 when most of the 13 targeted §12.2 metrics pass **and** constraint satisfaction, clarification behaviour, infeasibility handling and grounding each pass or miss only narrowly with a stated cause. Every miss is listed in [Where we fall short](#where-we-fall-short). Otherwise the claim drops to D1, here and in the deck (ADR 0089 D3).

## Evidence matrix

SPEC §16, filled in. Code paths are under `backend/src/promopilot/`; pytest ids are under `backend/`; frontend paths are under `frontend/`. Each row's full evidence is in its subsection below.

| Claim | Evidence in code | Test(s) | Demo moment | Eval metric |
|---|---|---|---|---|
| [F-01 Select products](#f-01-select-which-products-to-promote) | `optimizer/solver.py`, `optimizer/options.py` | hard-constraint property tests, not-selected reasons | plan table + "Not selected" list | plan quality, regret |
| [F-02 Mechanism](#f-02-determine-the-promotion-mechanism) | `mechanisms/compare.py`, `models/response.py` | comparator tests | mechanism drawer | plan quality |
| [F-03 Discount + strategy](#f-03-optimise-the-discount-and-customise-other-strategies) | `optimizer/`, `models/demand.py`, `models/response.py` | monotonicity property tests | depth / duration / segment columns, uplift by segment | elasticity recovery |
| [F-04 Cannibalisation](#f-04-understand-cannibalisation) | `models/relations.py`, strong-substitute rule | substitute detection and cross-effect tests | cannibalisation callout | substitute P/R, heavy-cannibalisation scenarios |
| [F-05 Relationships](#f-05-understand-product-relationships) | `models/relations.py`, `mechanisms/compare.py` | complement and halo tests | bundle suggestion + halo | complement P/R |
| [F-06 Inventory](#f-06-consider-inventory-constraints) | optimiser stock and clearance constraints, `guardrails/validation.py` | stock and clearance constraint tests | stock-out risk column, clearance met | constraint satisfaction, oracle breach rate |
| [F-07 Geography](#f-07-geographically-customise-promotions) | one joint solve over region-level plan lines | region tests | region tabs side by side | regional holiday scenarios |
| [F-08 Competitor](#f-08-competitor-awareness) | `competitors/gaps.py`, price-match options, KVI tolerance | competitor tests | competitor panel | competitor price-war scenarios |
| [F-09 Simulation](#f-09-simulate-the-promotion-before-launching) | `simulator/simulate.py` | determinism + invariant tests | P10–P90 chart | — |
| [D2 reliability](#d2-reliability) | `evals/` | eval runner tests | `/evals` dashboard | all §12.2 metrics |
| [Supporting features](#supporting-features) | trace, logs, retrain, fallback, approval, grounding | agent + API tests | trace timeline, approve step | grounding, consistency |

### F-01 Select which products to promote

- **Code.**
  - `optimizer/solver.py` `solve`: a CP-SAT model that picks at most one promo option per SKU and region (ADR 0036).
  - `optimizer/options.py` `generate_options`: the candidate set, pruned of options whose P90 units exceed available stock.
  - Each plan line says why it was chosen, and the top five not-selected options say why not (`domain/selection.py`, ADR 0067).
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_every_returned_plan_satisfies_every_hard_constraint` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_only_lines_with_a_positive_value_are_selected`
  - `tests/unit/optimizer/test_solve_reports.py::test_every_plan_line_says_why_and_every_listed_option_says_why_not` (hypothesis)
  - `tests/unit/optimizer/test_solve_reports.py::test_at_most_five_are_listed_best_value_first`
  - `frontend/tests/unit/not-selected-list.test.tsx`, `frontend/tests/unit/plan-table.test.tsx`
- **Demo moment.** The "Diwali demo" example brief: the plan table per region and the "Not selected" list (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.**
  - Plan quality: <!-- LATE --> _pending_ (target ≥ 90%).
  - Regret, median: <!-- LATE --> _pending_ (target ≤ 10%). Regret by cause: model error <!-- LATE --> _pending_, planner <!-- LATE --> _pending_, timeouts <!-- LATE --> _pending_ (ADR 0078).

### F-02 Determine the promotion mechanism

- **Code.**
  - `mechanisms/compare.py` `compare`: for each plan line, the best option of each mechanism (`PCT_OFF`, `BOGO`, `BUNDLE`, `FIXED_PRICE`) with its expected profit, units and margin (ADR 0041). The planner calls it through `agents/tools/compare_mechanisms.py`.
  - `models/response.py`: mechanism effects are fitted from promo history, not hard-coded (ADR 0024).
  - `optimizer/options.py`: a `BUNDLE` is generated only with a detected complement.
- **Tests.**
  - `tests/unit/mechanisms/test_compare.py::test_each_mechanism_shows_its_best_option_by_value_with_that_options_numbers`
  - `tests/unit/mechanisms/test_compare.py::test_bundle_is_compared_only_for_a_sku_with_a_complement`
  - `tests/unit/mechanisms/test_compare.py::test_the_comparison_is_deterministic`
  - `tests/unit/models/test_promo_response.py::test_mechanism_effects_are_estimated_from_promo_history`
  - `tests/unit/optimizer/test_generate_options.py::test_a_bundle_appears_only_with_a_detected_complement_even_outside_the_scope`
  - `frontend/tests/unit/mechanism-drawer.test.tsx`
- **Demo moment.** "Compare mechanisms for …" on a plan line opens the mechanism drawer with the chosen mechanism marked (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.** Plan quality: <!-- LATE --> _pending_. There is no mechanism-specific metric; the mechanism is one of the decisions the oracle scores.

### F-03 Optimise the discount and customise other strategies

- **Code.**
  - `optimizer/options.py`: options over depth (5–50%), duration (1–4 weeks), target segment (one segment or All customers, ADR 0006) and start week inside the promo window (ADR 0005).
  - `optimizer/solver.py`: the objective chooses among them under the budget, margin and caps.
  - `models/demand.py` and `models/response.py`: the baseline forecast and the promo response with own-price elasticities per segment (ADR 0023, ADR 0024).
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_lowering_the_budget_never_deepens_the_average_discount` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_raising_the_minimum_margin_never_deepens_the_average_discount` (hypothesis)
  - `tests/unit/optimizer/test_solve.py::test_tightening_the_budget_never_increases_the_objective` (hypothesis)
  - `tests/unit/optimizer/test_generate_options.py::test_every_option_starts_and_ends_inside_the_promo_window`
  - `tests/unit/optimizer/test_generate_options.py::test_both_segment_targeted_and_all_customers_options_are_present`
  - `tests/unit/models/test_promo_response.py::test_a_segment_exclusive_offer_changes_only_that_segment`
  - `tests/unit/models/test_promo_response.py::test_recovered_elasticities_are_close_to_the_true_ones`
- **Demo moment.** The depth, duration and segment columns of each plan line, and the "Uplift by segment" table in its details (`frontend/tests/e2e/brief-to-plan.spec.ts`).
- **Eval metric.** Elasticity recovery, median absolute % error: <!-- LATE --> _pending_ (target ≤ 20%).

### F-04 Understand cannibalisation

- **Code.**
  - `models/relations.py` `fit`: substitutes from cross-price effects within each subcategory, kept at a Benjamini–Hochberg q below 0.05 and a minimum effect size (ADR 0013, ADR 0029).
  - `models/relations.py` `line_effects` and `pairwise_cannibalisation`: plan value is net of cannibalised sister-SKU profit, per plan line and per pair (ADR 0033).
  - `optimizer/solver.py` and `guardrails/validation.py`: strong substitutes are never promoted together in the same region, week and segment (ADR 0075).
- **Tests.**
  - `tests/unit/models/test_relations.py::test_a_substitute_needs_a_bh_q_below_005_and_the_minimum_effect_size`
  - `tests/unit/models/test_relations.py::test_substitutes_are_detected_with_good_precision_and_recall`
  - `tests/unit/models/test_cross_effects.py::test_a_line_cannibalises_every_substitute_in_its_region_in_scope_or_not`
  - `tests/unit/optimizer/test_solve_substitutes.py::test_two_strong_substitutes_are_never_promoted_together`
  - `tests/unit/guardrails/test_validate_plan.py::test_two_strong_substitutes_promoted_together_are_flagged`
  - `frontend/tests/unit/cross-effect-callouts.test.tsx`
- **Demo moment.** The cannibalisation callout on a plan line: "Promoting A reduces B's units by N%". <!-- LATE: confirm the re-recorded demo session shows a cannibalisation callout; otherwise cite the heavy-cannibalisation scenarios (ADR 0089 D9) -->
- **Eval metric.**
  - Substitute detection: precision <!-- LATE --> _pending_ (target ≥ 0.8), recall <!-- LATE --> _pending_ (target ≥ 0.7).
  - Heavy-cannibalisation scenarios passing `no_strong_substitutes_together`: <!-- LATE --> _pending_ of 3.

### F-05 Understand product relationships

- **Code.**
  - `models/relations.py` `fit`: complements from basket co-occurrence (lift above a threshold, with minimum support) and negative cross-price effects (ADR 0029).
  - `models/relations.py` `line_effects`: halo on complements is added to plan value and shown per plan line (ADR 0033).
  - `mechanisms/compare.py`: a bundle suggestion lists the pair, its lift and its expected incremental profit.
- **Tests.**
  - `tests/unit/models/test_relations.py::test_complements_need_lift_above_the_threshold_and_minimum_support`
  - `tests/unit/models/test_relations.py::test_complements_are_detected_with_good_precision_and_recall`
  - `tests/unit/models/test_cross_effects.py::test_a_line_lifts_a_complement_in_its_region_and_counts_it_as_halo`
  - `tests/unit/mechanisms/test_compare.py::test_a_bundle_suggestion_lists_the_pair_its_lift_and_its_incremental_profit`
  - `frontend/tests/unit/cross-effect-callouts.test.tsx`
- **Demo moment.** The halo callout on a plan line and the `BUNDLE` row of the mechanism drawer. <!-- LATE: confirm a re-recorded session holds a BUNDLE line or a halo callout; otherwise cite tests/unit/mechanisms/test_compare.py and the eval's complement recovery (ADR 0089 D9) -->
- **Eval metric.** Complement detection: precision <!-- LATE --> _pending_ (target ≥ 0.8), recall <!-- LATE --> _pending_ (target ≥ 0.7).

### F-06 Consider inventory constraints

- **Code.**
  - `optimizer/options.py`: options whose P90 units exceed available stock are pruned before the solve.
  - `optimizer/solver.py`: clearance targets for overstocked SKUs the brief names; an unreachable target gives the closest plan with its clearance shortfall, and the revision is `INFEASIBLE` (ADR 0040, ADR 0074).
  - `guardrails/validation.py` `validate_plan`: every hard constraint checked on plan-time values (ADR 0012).
  - Plans keep a safety margin: the budget at P90 promo cost, stock with a 2σ buffer, the margin at P10 units (ADR 0080). <!-- LATE: #159 (PR #177) — confirm merged; code in guardrails/safety.py and domain/safety.py -->
  - `simulator/simulate.py`: stock-out probability per plan line.
- **Tests.**
  - `tests/unit/optimizer/test_generate_options.py::test_options_whose_p90_units_exceed_available_stock_are_pruned`
  - `tests/unit/guardrails/test_validate_plan.py::test_p90_units_above_available_stock_are_flagged_per_line`
  - `tests/unit/optimizer/test_solve_constraints.py::test_a_clearance_target_is_met_even_by_a_line_that_loses_money`
  - `tests/unit/optimizer/test_solve_constraints.py::test_an_unreachable_clearance_target_gives_the_closest_plan_and_reports_the_shortfall`
  - `tests/unit/simulator/test_simulate.py::test_stock_out_probability_is_one_with_no_stock`
  - <!-- LATE: #159 test ids from tests/unit/optimizer/test_solve_safety_margin.py and tests/unit/guardrails/test_safety_margin.py --> _pending_
  - `frontend/tests/unit/constraint-checklist.test.tsx`
- **Demo moment.** The "Diwali demo" brief clears at least 60% of its overstocked 400g namkeen packs: the stock-out risk column, and the constraint checklist's Clearance row reads Pass in every revision. <!-- LATE: #142 (PR #180) makes the demo feasible; confirm on the re-recorded demo session and cite frontend/tests/e2e/amend.spec.ts -->
- **Eval metric.**
  - Constraint satisfaction: <!-- LATE --> _pending_ (target 100%).
  - Oracle breach rate: <!-- LATE --> _pending_ (target ≤ 15%, ADR 0080).
  - Overstock-clearance scenarios passing: <!-- LATE --> _pending_ of 4.

### F-07 Geographically customise promotions

- **Code.**
  - One joint solve over region-level plan lines with pooled regional stock (ADR 0004): each region gets its own lines from its own demand, stock, segment mix, holidays and competitor prices, under one shared budget.
  - Regional budget caps (ADR 0040) in `optimizer/solver.py`.
- **Tests.**
  - `tests/unit/optimizer/test_solve.py::test_per_region_plans_follow_regional_holidays`
  - `tests/unit/optimizer/test_solve_constraints.py::test_a_regional_budget_cap_limits_the_promo_cost_spent_in_its_region`
  - `tests/unit/models/test_cross_effects.py::test_a_line_has_no_effect_in_another_region`
  - `frontend/tests/unit/region-plan-tabs.test.tsx`
- **Demo moment.**
  - Region tabs and "Compare regions" side by side (`frontend/tests/e2e/brief-to-plan.spec.ts`); "Christmas, every region" plans all regions with a ₹1 lakh cap on South.
  - Regional holidays are not in the demo recordings. They are shown by the scenarios `pongal-2026-south`, `durga-puja-2025-east` and `lohri-2026-north` and by `test_per_region_plans_follow_regional_holidays` (ADR 0089 D9).
- **Eval metric.** Regional-holiday scenarios passing: <!-- LATE --> _pending_ of 3.

### F-08 Competitor awareness

- **Code.**
  - `competitors/gaps.py` `competitor_gaps`: competitor price index and gap per SKU and region, and the undercut flag for KVIs past the company-policy threshold (ADR 0031).
  - `models/response.py`: the competitor price index is a demand-model input.
  - `optimizer/options.py`: an undercut KVI gets a price-match option in its region.
  - The optional KVI tolerance keeps KVI promo prices near the competitor's (`optimizer/solver.py`, `guardrails/validation.py`).
  - The planner states each undercut and its response in a planner note, grounded against the gaps.
- **Tests.**
  - `tests/unit/competitors/test_competitor_gaps.py::test_with_the_default_threshold_a_4_9_pct_gap_is_not_undercut_and_5_1_pct_is`
  - `tests/unit/competitors/test_competitor_gaps.py::test_a_partial_response_says_how_many_of_the_undercut_skus_it_matches`
  - `tests/unit/models/test_promo_response.py::test_a_competitor_undercut_lowers_predicted_units`
  - `tests/unit/optimizer/test_generate_options.py::test_an_undercut_kvi_gets_a_price_match_option_in_its_region`
  - `tests/unit/optimizer/test_solve_constraints.py::test_the_kvi_tolerance_keeps_kvi_promo_prices_near_the_competitor_when_enabled`
  - `tests/unit/agents/test_planner_agent.py::test_an_undercut_kvi_is_explained_with_its_gap_and_the_plans_response`
  - `frontend/tests/unit/competitor-panel.test.tsx`, `frontend/tests/unit/undercut-callout.test.tsx`
- **Demo moment.** The competitor panel on "Christmas, every region", which keeps KVIs within 3% of competitor prices.
- **Eval metric.** Competitor price-war scenarios passing: <!-- LATE --> _pending_ of 4.

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
- **Demo moment.** The "Simulated gross profit by plan line" band chart, and Re-simulate with a competitor reaction.
- **Eval metric.** — (SPEC §16). The simulator's accuracy is not scored against the oracle; its determinism, quantile order and speed are tested.

### D2 reliability

- **Code.** `evals/`: `runner.py` plays each scenario through the real agent graph; `metrics.py`, `behaviour.py`, `quality.py` and `recovery.py` score it; `oracle.py` judges plans on true demand; `report.py` writes the JSON and Markdown report (ADR 0056, ADR 0062–0064). Scenarios are `backend/evals/scenarios/*.yaml`.
- **Tests.**
  - `tests/evals/test_runner.py::test_the_run_is_deterministic_for_a_seed`
  - `tests/evals/test_runner.py::test_every_scored_plan_is_compared_with_the_rule_based_baseline_and_the_best_plan`
  - `tests/evals/test_suite.py::test_the_suite_has_at_least_the_spec_count_in_every_group_and_30_in_all`
  - `tests/evals/test_quality.py::test_regret_is_the_median_over_scored_runs_against_at_most_10_percent`
  - `tests/architecture/test_ground_truth_boundary.py::test_only_datagen_and_evals_reference_the_ground_truth`
  - `frontend/tests/e2e/evals.spec.ts`
- **Demo moment.** The `/evals` dashboard: metric cards against targets, the regret chart and the per-scenario table.
- **Eval metric.** All of SPEC §12.2: see [Final eval numbers](#final-eval-numbers).

### Supporting features

| Feature | Code | Tests | Demo moment |
|---|---|---|---|
| SF-01 Observability | `agents/trace.py`, the SSE route in `api/sessions.py`, `logs.py`, `llm/usage.py` (ADR 0047, ADR 0085) | `tests/unit/agents/test_graph_trace.py::test_a_planning_run_traces_every_node_in_order_up_to_the_approval_pause`, `tests/integration/test_session_events_api.py::test_the_stream_sends_every_event_in_order_then_ends_once_approved`, `tests/integration/test_session_logs_api.py::test_every_line_of_a_session_request_carries_the_request_and_session_ids`, `tests/unit/llm/test_usage.py::test_totals_add_tokens_and_price_each_call_by_its_model` | the trace timeline and the usage meter |
| SF-02 Trainability | `models/training.py`, `models/registry.py`, `api/models.py` (ADR 0026) | `tests/integration/test_models_api.py::test_retrain_registers_a_new_version_that_becomes_the_latest_and_live` | the `/models` page's retrain button |
| SF-03 Fault tolerance | `llm/resilience.py`, `agents/fallback.py`, `agents/checkpoints.py`, `llm/replay.py` (ADR 0027, ADR 0053) | `tests/unit/llm/test_resilience.py::test_after_the_primary_exhausts_its_retries_the_secondary_answers`, `tests/unit/agents/test_graph.py::test_with_the_llm_down_at_context_the_demo_brief_still_reaches_a_plan`, `tests/integration/test_sessions_api.py::test_approval_after_a_restart_resumes_the_graph_from_its_checkpoint` | `make demo` replays every example brief with no API key |
| SF-04 Human oversight | the approval interrupt in `agents/graph.py`; approve and reject in `api/sessions.py` (ADR 0046) | `tests/unit/agents/test_graph.py::test_rejecting_records_the_reason_and_waits_at_approval_again`, `frontend/tests/e2e/approve.spec.ts`, `frontend/tests/e2e/reject.spec.ts` | approve after a confirm, reject with a reason, the audit trail |
| SF-05 Explainability | `guardrails/grounding.py` `check_numeric_grounding`, `agents/explainer.py` (ADR 0028, ADR 0050) | `tests/unit/agents/test_grounded_explainer.py::test_a_second_ungrounded_answer_falls_back_to_the_template`, `tests/architecture/test_recorded_sessions_are_grounded.py::test_every_number_in_a_recorded_explanation_or_critique_is_in_its_tool_data` | each plan line's rationale; every number's source tooltip |

Eval metrics: grounding <!-- LATE --> _pending_ (target ≥ 98%); consistency <!-- LATE --> _pending_ (target ≥ 0.9).

## Agentic capabilities

SPEC §5 AG-01…AG-06, judged under evaluation criterion 5 (ADR 0089 D6).

| Capability | Code | Tests | Demo moment | Eval metric |
|---|---|---|---|---|
| AG-01 Parameter extraction | `agents/context.py`, `agents/resolution.py`, `agents/assumptions.py` (ADR 0048) | `tests/unit/agents/test_context_agent.py::test_a_brief_stating_every_critical_field_becomes_a_request_with_its_assumptions` | the assumptions panel with source and confidence | extraction accuracy <!-- LATE --> _pending_ (≥ 95%) |
| AG-02 Clarification | the Clarify interrupt in `agents/graph.py` | `tests/unit/agents/test_graph.py::test_a_missing_budget_routes_to_clarify_and_the_answer_resumes_to_the_planner`, `frontend/tests/e2e/clarify.spec.ts` | "No budget: the agent asks" | clarification behaviour <!-- LATE --> _pending_ (100%) |
| AG-03 Tool use | `agents/planner_agent.py`, `agents/tools/registry.py` (ADR 0025, ADR 0049) | `tests/unit/agents/test_planner_agent.py::test_scripted_tool_calls_on_the_small_world_produce_the_optimised_plan_each_traced`, `tests/unit/agents/test_tool_registry.py::test_arguments_that_break_the_input_schema_give_a_typed_error` | tool calls with arguments and results in the trace timeline | — |
| AG-04 Self-correction | `agents/critic.py`, `guardrails/risks.py` (ADR 0051, ADR 0059) | `tests/unit/agents/test_critic_loop.py::test_violations_loop_to_the_planner_at_most_3_times_then_go_to_the_explainer`, <!-- LATE: #141 (PR #178) tests/unit/agents/test_critic_loop.py::test_a_finding_goes_away_when_the_next_attempt_caps_its_skus_depth --> _pending_ | Critic findings and decisions in the trace | open issues per final plan <!-- LATE --> _pending_ (report) |
| AG-05 Dynamic re-planning | `agents/amendments.py`, `guardrails/diff.py` (ADR 0052) | `tests/unit/agents/test_amend.py::test_cutting_the_budget_plans_a_new_revision_within_it_with_a_diff`, `frontend/tests/e2e/amend.spec.ts` | "Budget cut to ₹6 lakh", then "Drop West": the revision diff | mid-plan amendment scenarios <!-- LATE --> _pending_ of <!-- LATE: 4 after #142 --> _pending_ |
| AG-06 Infeasibility handling | `optimizer/relaxation.py`, `agents/tools/relax_constraints.py` (ADR 0044, ADR 0083) | `tests/unit/optimizer/test_solve_relaxation.py::test_infeasible_instances_are_reported_infeasible_with_a_relaxation` (hypothesis), <!-- LATE: #142 (PR #180) frontend/tests/e2e/infeasible.spec.ts --> _pending_ | the infeasibility panel: binding constraints, the smallest relaxation, accept and re-plan <!-- LATE: #142's recorded `infeasible` session --> | infeasibility handling <!-- LATE --> _pending_ (100%) |

## Final eval numbers

Copied from `backend/evals/published/latest.md`, generated <!-- LATE: generated_at --> _pending_ (<!-- LATE: provider --> _pending_ provider, seed-42 world, <!-- LATE: scenario count --> _pending_ scenarios, 1 run each).

| Metric | Value | Target | Result |
|---|---|---|---|
| Constraint satisfaction | <!-- LATE --> _pending_ | 100% | <!-- LATE --> |
| Oracle breach rate | <!-- LATE --> _pending_ | ≤ 15% (ADR 0080) | <!-- LATE --> |
| Extraction accuracy | <!-- LATE --> _pending_ | ≥ 95% | <!-- LATE --> |
| Clarification behaviour | <!-- LATE --> _pending_ | 100% | <!-- LATE --> |
| Infeasibility handling | <!-- LATE --> _pending_ | 100% | <!-- LATE --> |
| Grounding | <!-- LATE --> _pending_ | ≥ 98% | <!-- LATE --> |
| Elasticity recovery (median abs % error) | <!-- LATE --> _pending_ | ≤ 20% | <!-- LATE --> |
| Substitute precision / recall | <!-- LATE --> _pending_ | ≥ 0.8 / ≥ 0.7 | <!-- LATE --> |
| Complement precision / recall | <!-- LATE --> _pending_ | ≥ 0.8 / ≥ 0.7 | <!-- LATE --> |
| Baseline WAPE (region × SKU, store × SKU, store × SKU × segment) | <!-- LATE --> _pending_ | report (aim ≤ 25%) | — |
| Plan quality (beats the rule-based baseline) | <!-- LATE --> _pending_ | ≥ 90% | <!-- LATE --> |
| Regret (median, against the best plan) | <!-- LATE --> _pending_ | ≤ 10% | <!-- LATE --> |
| Consistency (Jaccard across 5 runs) | <!-- LATE: from the supplementary report --> _pending_ | ≥ 0.9 | <!-- LATE --> |
| Open issues per final plan (median) | <!-- LATE: #141 --> _pending_ | report | — |
| P50 session time | <!-- LATE --> _pending_ | report (SPEC §6: under 60 s) | — |
| P50 session cost | <!-- LATE --> _pending_ | report (SPEC §6: under ₹20) | — |

Scenarios passing by group:

| Group | Passing |
|---|---|
| Standard festive plans | <!-- LATE --> _pending_ of 6 |
| Tight budget | <!-- LATE --> _pending_ of 4 |
| Overstock clearance | <!-- LATE --> _pending_ of 4 |
| Competitor price war | <!-- LATE --> _pending_ of 4 |
| Regional holidays | <!-- LATE --> _pending_ of 3 |
| Heavy cannibalisation | <!-- LATE --> _pending_ of 3 |
| Vague or conflicting briefs | <!-- LATE --> _pending_ of 3 |
| Infeasible constraints | <!-- LATE --> _pending_ of 2 |
| Mid-plan amendments | <!-- LATE --> _pending_ of <!-- LATE: 4 after #142 --> |

### Consistency

Under replay a scenario's runs are identical by construction (ADR 0063), so consistency is measured by a supplementary live run: `make eval RUNS=5 SMOKE=1` (the five smoke scenarios, five runs each), generated <!-- LATE: generated_at of the consistency report --> _pending_ with the <!-- LATE: provider --> _pending_ provider. Mean Jaccard of selected SKUs: <!-- LATE --> _pending_ (target ≥ 0.9).

## Where we fall short

Every miss against a §12.2 target or a SPEC §6 requirement, with its cause (ADR 0089 D3, D8).

<!-- LATE: list each failing metric from the final report with its cause (regret by cause for regret; the failing scenarios for constraint satisfaction) and its ticket. Expected candidates, to confirm or drop: regret median against 10%; constraint satisfaction against 100%; the oracle breach rate against 15%; consistency. -->

- **Latency.** SPEC §6 asks for a full plan in under 60 s with a real LLM. The P50 session takes <!-- LATE --> _pending_, of which <!-- LATE --> _pending_ is waiting on the LLM; the slowest takes <!-- LATE --> _pending_. <!-- LATE: #113 (candidate generation speed) — state whether it merged and what it saved --> Cost per session, <!-- LATE --> _pending_, is within the ₹20 target.

## Reproduce the numbers

- `make eval`: every scenario once on the seed-42 world, into `backend/evals/reports/` (`<timestamp>.json` and `.md`, plus `latest.*`). With no API key it replays the committed cassettes.
- `make eval RUNS=5 SMOKE=1`: the consistency run. It measures something only with a live LLM (`OPENAI_API_KEY`).
- `make eval-smoke`: what CI runs on every PR, five scenarios with no key.
- The `/evals` page shows the latest report; `make demo` serves the published one from `backend/evals/published/`.

See the README's [Evals](../README.md#evals) section for scenario format, metrics and options.
