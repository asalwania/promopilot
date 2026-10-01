# PromoPilot eval report

Generated 2026-10-01T17:07:27.698874+00:00 with the `replay` provider on the seed-42 world: 33 scenarios, 1 run(s) each, 33 sessions.

## Metrics

| Metric | Value | Target | Result |
|---|---|---|---|
| Constraint satisfaction | 100.0% (30 of 30) | ≥ 100% | pass |
| Oracle breach rate | 13.3% (4 of 30) | ≤ 15% | pass |
| Open issues per plan (median) | 1 (21 of 33) | report | — |
| Extraction accuracy | 100.0% (152 of 152) | ≥ 95% | pass |
| Clarification behaviour | 100.0% (3 of 3) | ≥ 100% | pass |
| Infeasibility handling | 100.0% (2 of 2) | ≥ 100% | pass |
| Grounding | 100.0% (39 of 39) | ≥ 98% | pass |
| P50 session time | 18.0 s (33 of 33) | report | — |
| P50 session cost | ₹3.52 (33 of 33) | report | — |
| Elasticity recovery (median abs % error) | 8.1% (679 of 800) | ≤ 20% | pass |
| Substitute precision | 86.7% (91 of 105) | ≥ 80% | pass |
| Substitute recall | 100.0% (91 of 91) | ≥ 70% | pass |
| Complement precision | 100.0% (39 of 39) | ≥ 80% | pass |
| Complement recall | 97.5% (39 of 40) | ≥ 70% | pass |
| Baseline WAPE, store x SKU x segment | 43.5% | report (aim ≤ 25%) | — |
| Baseline WAPE, store x SKU | 25.1% | report (aim ≤ 25%) | — |
| Baseline WAPE, region x SKU | 13.5% | report (aim ≤ 25%) | — |
| Plan quality (beats the rule-based baseline) | 100.0% (30 of 30) | ≥ 90% | pass |
| Regret (median, against the best plan) | 12.3% (12 of 29) | ≤ 10% | **fail** |
| Consistency (Jaccard of selected SKUs across runs) | n/a | ≥ 90% | — |

- Constraint satisfaction: failed 0, infeasible 3, no_plan 0
- Oracle breach rate: promo_cost_over_budget 2, margin_below_minimum 0, demand_over_stock 3
- Open issues per plan (median): total 41, HEAVY_CANNIBALISATION 18, OVER_CONCENTRATION 14, CLEARANCE_TARGET 9
- Clarification behaviour: asked 2, flagged_only 1, neither 0, unneeded_asks 0
- Infeasibility handling: not_declared 0, no_relaxation 0, nothing_binds 0, no_plan 0
- Grounding: llm 39, ungrounded 0, invalid_answer 0, llm_unavailable 0
- P50 session time: max_s 131, llm_p50_s 0
- P50 session cost: calls 446, input_tokens 3446566, output_tokens 79094, unpriced_runs 0
- Plan quality (beats the rule-based baseline): beats 30, ties 0, loses 0
- Regret (median, against the best plan): best_infeasible 1, best_timed_out 0, largest_model_error 16, largest_planner 1, largest_timeouts 0

## Scenarios

| Scenario | Group | Run | Outcome | Plan | Constraints | Oracle breaches | Properties | Result |
|---|---|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | mid_plan_amendments | 1 | planned | rev 3: 20 lines, OPTIMAL | passed | demand_over_stock | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 1 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| cannibal-bakery-diwali-2026 | heavy_cannibalisation | 1 | planned | rev 1: 6 lines, OPTIMAL | passed | none | 2/2 | pass |
| cannibal-frozen-christmas-2025 | heavy_cannibalisation | 1 | planned | rev 1: 15 lines, OPTIMAL | passed | none | 2/2 | pass |
| cannibal-personal-care-offseason | heavy_cannibalisation | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 2/2 | pass |
| christmas-2025-bakery-beverages | standard_festive | 1 | planned | rev 1: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| christmas-2026-frozen-snacks | standard_festive | 1 | planned | rev 1: 25 lines, OPTIMAL | passed | none | 2/2 | pass |
| clear-curd-diwali-2025 | overstock_clearance | 1 | planned | rev 1: 17 lines, INFEASIBLE | infeasible | — | 1/1 | pass |
| clear-dishwash-offseason | overstock_clearance | 1 | planned | rev 1: 6 lines, OPTIMAL | passed | none | 3/3 | pass |
| clear-juices-christmas-2025 | overstock_clearance | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 2/2 | pass |
| clear-shampoo-diwali-2026 | overstock_clearance | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 2/2 | pass |
| conflict-margin-below-floor | vague_or_conflicting | 1 | planned | rev 1: 9 lines, OPTIMAL | passed | none | 2/2 | pass |
| demo-budget-cut-drop-west | mid_plan_amendments | 1 | planned | rev 3: 11 lines, OPTIMAL | passed | none | 5/5 | pass |
| diwali-2025-home-personal-care | standard_festive | 1 | planned | rev 1: 75 lines, OPTIMAL | passed | demand_over_stock | 1/1 | pass |
| diwali-2025-snacks-beverages-east-cap | standard_festive | 1 | planned | rev 1: 66 lines, OPTIMAL | passed | none | 1/1 | pass |
| diwali-2026-staples-dairy-margin | standard_festive | 1 | planned | rev 1: 19 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 1 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 1 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| durga-puja-2025-east | regional_holidays | 1 | planned | rev 1: 19 lines, OPTIMAL | passed | none | 4/4 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 1 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-tiny-budget | infeasible_constraints | 1 | planned | rev 1: 3 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-tiny-budget-accept | mid_plan_amendments | 1 | planned | rev 2: 2 lines, OPTIMAL | passed | none | 4/4 | pass |
| lohri-2026-north | regional_holidays | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 4/4 | pass |
| pongal-2026-south | regional_holidays | 1 | planned | rev 1: 11 lines, OPTIMAL | passed | none | 4/4 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 1 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-home-care-diwali-2025 | competitor_price_war | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | promo_cost_over_budget | 2/2 | pass |
| price-war-home-care-staples-diwali-2026 | competitor_price_war | 1 | planned | rev 1: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-staples-christmas-2025 | competitor_price_war | 1 | planned | rev 1: 2 lines, OPTIMAL | passed | none | 2/2 | pass |
| tight-christmas-2025-bakery | tight_budget | 1 | planned | rev 1: 4 lines, OPTIMAL | passed | none | 2/2 | pass |
| tight-diwali-2025-snacks | tight_budget | 1 | planned | rev 1: 7 lines, OPTIMAL | passed | none | 1/1 | pass |
| tight-diwali-2026-personal-care | tight_budget | 1 | planned | rev 1: 8 lines, OPTIMAL | passed | promo_cost_over_budget, demand_over_stock | 1/1 | pass |
| tight-offseason-beverages | tight_budget | 1 | planned | rev 1: 6 lines, OPTIMAL | passed | none | 1/1 | pass |
| vague-no-category | vague_or_conflicting | 1 | planned | rev 1: 10 lines, OPTIMAL | passed | none | 2/2 | pass |

## Agent behaviour

| Scenario | Run | Extraction | Asked | Flagged | Explainer | Session | Cost |
|---|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | 1 | 4/4 | — | — | llm, llm, llm | 67.0 s (LLM 0.1 s) | ₹9.19, 29 calls |
| amend-budget-cut-christmas-2025 | 1 | 4/4 | — | — | llm, llm | 88.2 s (LLM 0.1 s) | ₹13.56, 40 calls |
| cannibal-bakery-diwali-2026 | 1 | 4/4 | — | — | llm | 12.1 s (LLM 0.1 s) | ₹5.38, 21 calls |
| cannibal-frozen-christmas-2025 | 1 | 4/4 | — | — | llm | 15.6 s (LLM 0.1 s) | ₹6.05, 21 calls |
| cannibal-personal-care-offseason | 1 | 4/4 | — | — | llm | 53.2 s (LLM 0.0 s) | ₹3.21, 10 calls |
| christmas-2025-bakery-beverages | 1 | 4/4 | — | — | llm | 36.7 s (LLM 0.1 s) | ₹6.73, 21 calls |
| christmas-2026-frozen-snacks | 1 | 4/4 | — | — | llm | 18.0 s (LLM 0.1 s) | ₹5.18, 14 calls |
| clear-curd-diwali-2025 | 1 | 5/5 | — | — | llm | 54.0 s (LLM 0.0 s) | ₹4.48, 10 calls |
| clear-dishwash-offseason | 1 | 5/5 | — | — | llm | 35.3 s (LLM 0.0 s) | ₹3.20, 12 calls |
| clear-juices-christmas-2025 | 1 | 5/5 | — | — | llm | 21.8 s (LLM 0.0 s) | ₹1.84, 5 calls |
| clear-shampoo-diwali-2026 | 1 | 6/6 | — | — | llm | 130.5 s (LLM 0.1 s) | ₹7.06, 25 calls |
| conflict-margin-below-floor | 1 | 5/5 | — | min_margin | llm | 6.6 s (LLM 0.1 s) | ₹5.03, 19 calls |
| demo-budget-cut-drop-west | 1 | 5/5 | — | target_segment | llm, llm, llm | 22.3 s (LLM 0.1 s) | ₹9.82, 27 calls |
| diwali-2025-home-personal-care | 1 | 4/4 | — | — | llm | 86.4 s (LLM 0.1 s) | ₹5.76, 10 calls |
| diwali-2025-snacks-beverages-east-cap | 1 | 5/5 | — | — | llm | 51.7 s (LLM 0.1 s) | ₹5.30, 10 calls |
| diwali-2026-staples-dairy-margin | 1 | 5/5 | — | — | llm | 6.4 s (LLM 0.0 s) | ₹1.77, 5 calls |
| diwali-no-budget | 1 | 4/4 | marketing_budget | — | llm | 22.8 s (LLM 0.1 s) | ₹4.30, 12 calls |
| diwali-snacks-beverages | 1 | 4/4 | — | — | llm | 22.9 s (LLM 0.0 s) | ₹3.94, 10 calls |
| durga-puja-2025-east | 1 | 4/4 | — | — | llm | 6.5 s (LLM 0.1 s) | ₹3.52, 11 calls |
| infeasible-clearance-high-margin | 1 | 6/6 | — | — | llm | 20.7 s (LLM 0.0 s) | ₹3.52, 9 calls |
| infeasible-clearance-tiny-budget | 1 | 5/5 | — | — | llm | 3.9 s (LLM 0.0 s) | ₹2.26, 8 calls |
| infeasible-tiny-budget-accept | 1 | 5/5 | — | — | llm, llm | 7.5 s (LLM 0.1 s) | ₹4.55, 16 calls |
| lohri-2026-north | 1 | 4/4 | — | — | llm | 5.3 s (LLM 0.0 s) | ₹1.78, 5 calls |
| pongal-2026-south | 1 | 4/4 | — | — | llm | 5.7 s (LLM 0.0 s) | ₹2.61, 10 calls |
| price-war-bakery-beverages-offseason | 1 | 5/5 | — | — | llm | 9.1 s (LLM 0.0 s) | ₹2.96, 10 calls |
| price-war-home-care-diwali-2025 | 1 | 5/5 | — | — | llm | 9.1 s (LLM 0.0 s) | ₹2.05, 6 calls |
| price-war-home-care-staples-diwali-2026 | 1 | 6/6 | — | — | llm | 10.3 s (LLM 0.0 s) | ₹2.23, 6 calls |
| price-war-staples-christmas-2025 | 1 | 6/6 | — | — | llm | 1.8 s (LLM 0.0 s) | ₹1.46, 6 calls |
| tight-christmas-2025-bakery | 1 | 4/4 | — | — | llm | 3.3 s (LLM 0.0 s) | ₹2.55, 10 calls |
| tight-diwali-2025-snacks | 1 | 4/4 | — | — | llm | 4.9 s (LLM 0.0 s) | ₹2.78, 10 calls |
| tight-diwali-2026-personal-care | 1 | 5/5 | — | — | llm | 29.5 s (LLM 0.0 s) | ₹1.44, 5 calls |
| tight-offseason-beverages | 1 | 4/4 | — | — | llm | 58.7 s (LLM 0.1 s) | ₹5.67, 21 calls |
| vague-no-category | 1 | 4/4 | scope.categories | — | llm | 6.9 s (LLM 0.1 s) | ₹3.32, 12 calls |

## Plan quality

Oracle objective (incremental profit plus clearance value) of each scored plan, the rule-based baseline, the default sequence's plan and the best plan for its final request. Regret splits into model error (best - default) / best, the planner's choices (default - ours) / best, and timeouts, a part whose plans include one the solver stopped as FEASIBLE.

| Scenario | Run | Ours | Rule-based | Default sequence | Best | Regret | Model error | Planner | Timeouts | Against the baseline |
|---|---|---|---|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | 1 | ₹126,373 | ₹4,446 (1 of 10 sellers kept) | ₹126,373 (OPTIMAL, 20 lines) | ₹128,601 (OPTIMAL, 20 lines) | 1.7% | 1.7% | 0.0% | 0.0% | beats |
| amend-budget-cut-christmas-2025 | 1 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| cannibal-bakery-diwali-2026 | 1 | ₹15,679 | ₹-22,845 (2 of 10 sellers kept) | ₹15,679 (OPTIMAL, 6 lines) | ₹19,333 (OPTIMAL, 9 lines) | 18.9% | 18.9% | 0.0% | 0.0% | beats |
| cannibal-frozen-christmas-2025 | 1 | ₹88,425 | ₹-47,453 (2 of 10 sellers kept) | ₹88,425 (OPTIMAL, 15 lines) | ₹100,776 (OPTIMAL, 17 lines) | 12.3% | 12.3% | 0.0% | 0.0% | beats |
| cannibal-personal-care-offseason | 1 | ₹105,085 | ₹-37,831 (4 of 10 sellers kept) | ₹105,256 (OPTIMAL, 20 lines) | ₹101,198 (OPTIMAL, 20 lines) | -3.8% | -4.0% | 0.2% | 0.0% | beats |
| christmas-2025-bakery-beverages | 1 | ₹66,613 | ₹-85,841 (4 of 10 sellers kept) | ₹66,613 (OPTIMAL, 26 lines) | ₹84,127 (OPTIMAL, 27 lines) | 20.8% | 20.8% | 0.0% | 0.0% | beats |
| christmas-2026-frozen-snacks | 1 | ₹137,129 | ₹-64,745 (6 of 10 sellers kept) | ₹135,407 (OPTIMAL, 25 lines) | ₹138,911 (OPTIMAL, 27 lines) | 1.3% | 2.5% | -1.2% | 0.0% | beats |
| clear-dishwash-offseason | 1 | ₹31,071 | ₹4,446 (1 of 10 sellers kept) | ₹31,071 (OPTIMAL, 6 lines) | ₹36,616 (OPTIMAL, 7 lines) | 15.1% | 15.1% | 0.0% | 0.0% | beats |
| clear-juices-christmas-2025 | 1 | ₹50,112 | ₹-51,800 (3 of 10 sellers kept) | ₹50,112 (OPTIMAL, 20 lines) | ₹63,593 (OPTIMAL, 20 lines) | 21.2% | 21.2% | 0.0% | 0.0% | beats |
| clear-shampoo-diwali-2026 | 1 | ₹93,023 | ₹-30,597 (2 of 10 sellers kept) | ₹93,023 (OPTIMAL, 20 lines) | ₹81,043 (OPTIMAL, 20 lines) | -14.8% | -14.8% | 0.0% | 0.0% | beats |
| conflict-margin-below-floor | 1 | ₹14,554 | ₹-24,700 (8 of 10 sellers kept) | ₹14,554 (OPTIMAL, 9 lines) | ₹22,155 (OPTIMAL, 7 lines) | 34.3% | 34.3% | 0.0% | 0.0% | beats |
| demo-budget-cut-drop-west | 1 | ₹22,788 | ₹-41,795 (10 of 10 sellers kept) | ₹68,018 (OPTIMAL, 20 lines) | ₹74,803 (OPTIMAL, 19 lines) | 69.5% | 9.1% | 60.5% | 0.0% | beats |
| diwali-2025-home-personal-care | 1 | ₹469,065 | ₹0 (0 of 10 sellers kept) | ₹476,571 (OPTIMAL, 80 lines) | ₹521,562 (OPTIMAL, 72 lines) | 10.1% | 8.6% | 1.4% | 0.0% | beats |
| diwali-2025-snacks-beverages-east-cap | 1 | ₹278,763 | ₹-110,036 (2 of 10 sellers kept) | ₹295,493 (OPTIMAL, 71 lines) | ₹321,272 (OPTIMAL, 68 lines) | 13.2% | 8.0% | 5.2% | 0.0% | beats |
| diwali-2026-staples-dairy-margin | 1 | ₹108,241 | ₹-26,836 (1 of 10 sellers kept) | ₹108,241 (OPTIMAL, 19 lines) | ₹102,024 (OPTIMAL, 13 lines) | -6.1% | -6.1% | 0.0% | 0.0% | beats |
| diwali-no-budget | 1 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 1 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| durga-puja-2025-east | 1 | ₹93,896 | ₹-32,446 (4 of 10 sellers kept) | ₹93,896 (OPTIMAL, 19 lines) | ₹97,906 (OPTIMAL, 14 lines) | 4.1% | 4.1% | 0.0% | 0.0% | beats |
| infeasible-tiny-budget-accept | 1 | ₹8,072 | ₹0 (0 of 10 sellers kept) | ₹8,072 (OPTIMAL, 2 lines) | infeasible (INFEASIBLE, 2 lines) | — | — | — | — | beats |
| lohri-2026-north | 1 | ₹54,566 | ₹-46,815 (7 of 10 sellers kept) | ₹54,566 (OPTIMAL, 20 lines) | ₹65,088 (OPTIMAL, 20 lines) | 16.2% | 16.2% | 0.0% | 0.0% | beats |
| pongal-2026-south | 1 | ₹25,652 | ₹0 (0 of 10 sellers kept) | ₹25,652 (OPTIMAL, 11 lines) | ₹29,103 (OPTIMAL, 9 lines) | 11.9% | 11.9% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 1 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |
| price-war-home-care-diwali-2025 | 1 | ₹190,847 | ₹-85,621 (1 of 10 sellers kept) | ₹190,847 (OPTIMAL, 20 lines) | ₹174,542 (OPTIMAL, 20 lines) | -9.3% | -9.3% | 0.0% | 0.0% | beats |
| price-war-home-care-staples-diwali-2026 | 1 | ₹194,816 | ₹-122,041 (2 of 10 sellers kept) | ₹194,816 (OPTIMAL, 26 lines) | ₹189,541 (OPTIMAL, 26 lines) | -2.8% | -2.8% | 0.0% | 0.0% | beats |
| price-war-staples-christmas-2025 | 1 | ₹-153 | ₹-34,872 (2 of 10 sellers kept) | ₹-153 (OPTIMAL, 2 lines) | ₹1,575 (OPTIMAL, 1 lines) | 109.7% | 109.7% | 0.0% | 0.0% | beats |
| tight-christmas-2025-bakery | 1 | ₹7,850 | ₹0 (0 of 10 sellers kept) | ₹7,850 (OPTIMAL, 4 lines) | ₹9,403 (OPTIMAL, 4 lines) | 16.5% | 16.5% | 0.0% | 0.0% | beats |
| tight-diwali-2025-snacks | 1 | ₹39,574 | ₹-8,916 (2 of 10 sellers kept) | ₹39,574 (OPTIMAL, 7 lines) | ₹42,663 (OPTIMAL, 9 lines) | 7.2% | 7.2% | 0.0% | 0.0% | beats |
| tight-diwali-2026-personal-care | 1 | ₹130,797 | ₹6,541 (1 of 10 sellers kept) | ₹130,797 (OPTIMAL, 8 lines) | ₹112,339 (OPTIMAL, 8 lines) | -16.4% | -16.4% | 0.0% | 0.0% | beats |
| tight-offseason-beverages | 1 | ₹45,064 | ₹0 (0 of 10 sellers kept) | ₹45,064 (OPTIMAL, 6 lines) | ₹56,306 (OPTIMAL, 8 lines) | 20.0% | 20.0% | 0.0% | 0.0% | beats |
| vague-no-category | 1 | ₹23,302 | ₹-33,040 (4 of 10 sellers kept) | ₹23,302 (OPTIMAL, 10 lines) | ₹28,507 (OPTIMAL, 10 lines) | 18.3% | 18.3% | 0.0% | 0.0% | beats |

Regret by cause over the 29 counted runs (median, then ₹ in all): model error 9.1% (₹150,918), planner 0.0% (₹67,913), timeouts 0.0% (₹0).

Consistency needs at least two runs per scenario (`make eval RUNS=5`). Under the replay provider a scenario's runs are identical: only a live LLM varies them.

## Failures

None.
