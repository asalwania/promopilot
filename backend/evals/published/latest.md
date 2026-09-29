# PromoPilot eval report

Generated 2026-09-29T07:21:10.959318+00:00 with the `openai (recording)` provider on the seed-42 world: 32 scenarios, 1 run(s) each, 32 sessions.

## Metrics

| Metric | Value | Target | Result |
|---|---|---|---|
| Constraint satisfaction | 96.6% (28 of 29) | ≥ 100% | **fail** |
| Oracle breach rate | 41.4% (12 of 29) | report | — |
| Extraction accuracy | 100.0% (147 of 147) | ≥ 95% | pass |
| Clarification behaviour | 100.0% (3 of 3) | ≥ 100% | pass |
| Infeasibility handling | 100.0% (2 of 2) | ≥ 100% | pass |
| Grounding | 100.0% (37 of 37) | ≥ 98% | pass |
| P50 session time | 148.8 s (32 of 32) | report | — |
| P50 session cost | ₹3.04 (32 of 32) | report | — |
| Elasticity recovery (median abs % error) | 8.1% (679 of 800) | ≤ 20% | pass |
| Substitute precision | 86.7% (91 of 105) | ≥ 80% | pass |
| Substitute recall | 100.0% (91 of 91) | ≥ 70% | pass |
| Complement precision | 100.0% (39 of 39) | ≥ 80% | pass |
| Complement recall | 97.5% (39 of 40) | ≥ 70% | pass |
| Baseline WAPE, store x SKU x segment | 43.5% | report (aim ≤ 25%) | — |
| Baseline WAPE, store x SKU | 25.1% | report (aim ≤ 25%) | — |
| Baseline WAPE, region x SKU | 13.5% | report (aim ≤ 25%) | — |
| Plan quality (beats the rule-based baseline) | 93.1% (27 of 29) | ≥ 90% | pass |
| Regret (median, against the best plan) | 23.5% (12 of 29) | ≤ 10% | **fail** |
| Consistency (Jaccard of selected SKUs across runs) | n/a | ≥ 90% | — |

- Constraint satisfaction: failed 1, infeasible 3, no_plan 0
- Oracle breach rate: promo_cost_over_budget 7, margin_below_minimum 2, demand_over_stock 7
- Clarification behaviour: asked 2, flagged_only 1, neither 0, unneeded_asks 0
- Infeasibility handling: not_declared 0, no_relaxation 0, nothing_binds 0, no_plan 0
- Grounding: llm 37, ungrounded 0, invalid_answer 0, llm_unavailable 0
- P50 session time: max_s 868
- P50 session cost: calls 363, input_tokens 2735938, output_tokens 64236, unpriced_runs 0
- Plan quality (beats the rule-based baseline): beats 27, ties 2, loses 0
- Regret (median, against the best plan): best_infeasible 0

## Scenarios

| Scenario | Group | Run | Outcome | Plan | Constraints | Oracle breaches | Properties | Result |
|---|---|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | mid_plan_amendments | 1 | planned | rev 3: 20 lines, OPTIMAL | passed | promo_cost_over_budget, demand_over_stock | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 1 | planned | rev 2: 27 lines, OPTIMAL | passed | none | 2/2 | pass |
| cannibal-bakery-diwali-2026 | heavy_cannibalisation | 1 | planned | rev 1: 6 lines, OPTIMAL | passed | none | 1/2 | **fail** |
| cannibal-frozen-christmas-2025 | heavy_cannibalisation | 1 | planned | rev 1: 15 lines, OPTIMAL | passed | promo_cost_over_budget | 2/2 | pass |
| cannibal-personal-care-offseason | heavy_cannibalisation | 1 | planned | rev 1: 20 lines, FEASIBLE | passed | none | 1/2 | **fail** |
| christmas-2025-bakery-beverages | standard_festive | 1 | planned | rev 1: 12 lines, OPTIMAL | passed | none | 2/2 | pass |
| christmas-2026-frozen-snacks | standard_festive | 1 | planned | rev 1: 30 lines, OPTIMAL | passed | promo_cost_over_budget | 2/2 | pass |
| clear-curd-diwali-2025 | overstock_clearance | 1 | planned | rev 1: 19 lines, FEASIBLE | failed | none | 3/4 | **fail** |
| clear-dishwash-offseason | overstock_clearance | 1 | planned | rev 1: 6 lines, OPTIMAL | passed | none | 3/3 | pass |
| clear-juices-christmas-2025 | overstock_clearance | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 2/2 | pass |
| clear-shampoo-diwali-2026 | overstock_clearance | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | none | 2/2 | pass |
| conflict-margin-below-floor | vague_or_conflicting | 1 | planned | rev 1: 9 lines, OPTIMAL | passed | none | 2/2 | pass |
| demo-budget-cut-drop-west | mid_plan_amendments | 1 | planned | rev 3: 13 lines, INFEASIBLE | infeasible | — | 2/3 | **fail** |
| diwali-2025-home-personal-care | standard_festive | 1 | planned | rev 1: 0 lines, FEASIBLE | passed | none | 1/1 | pass |
| diwali-2025-snacks-beverages-east-cap | standard_festive | 1 | planned | rev 1: 71 lines, OPTIMAL | passed | demand_over_stock | 1/1 | pass |
| diwali-2026-staples-dairy-margin | standard_festive | 1 | planned | rev 1: 10 lines, OPTIMAL | passed | margin_below_minimum | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 1 | planned | rev 1: 37 lines, OPTIMAL | passed | promo_cost_over_budget, demand_over_stock | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 1 | planned | rev 1: 37 lines, OPTIMAL | passed | promo_cost_over_budget, demand_over_stock | 2/2 | pass |
| durga-puja-2025-east | regional_holidays | 1 | planned | rev 1: 16 lines, OPTIMAL | passed | none | 4/4 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 1 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-tiny-budget | infeasible_constraints | 1 | planned | rev 1: 2 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| lohri-2026-north | regional_holidays | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | demand_over_stock | 4/4 | pass |
| pongal-2026-south | regional_holidays | 1 | planned | rev 1: 12 lines, OPTIMAL | passed | margin_below_minimum | 4/4 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 1 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-home-care-diwali-2025 | competitor_price_war | 1 | planned | rev 1: 20 lines, OPTIMAL | passed | promo_cost_over_budget | 2/2 | pass |
| price-war-home-care-staples-diwali-2026 | competitor_price_war | 1 | planned | rev 1: 26 lines, OPTIMAL | passed | demand_over_stock | 2/2 | pass |
| price-war-staples-christmas-2025 | competitor_price_war | 1 | planned | rev 1: 2 lines, OPTIMAL | passed | none | 2/2 | pass |
| tight-christmas-2025-bakery | tight_budget | 1 | planned | rev 1: 3 lines, OPTIMAL | passed | none | 2/2 | pass |
| tight-diwali-2025-snacks | tight_budget | 1 | planned | rev 1: 15 lines, OPTIMAL | passed | none | 1/1 | pass |
| tight-diwali-2026-personal-care | tight_budget | 1 | planned | rev 1: 8 lines, OPTIMAL | passed | promo_cost_over_budget, demand_over_stock | 1/1 | pass |
| tight-offseason-beverages | tight_budget | 1 | planned | rev 1: 0 lines, FEASIBLE | passed | none | 1/1 | pass |
| vague-no-category | vague_or_conflicting | 1 | planned | rev 1: 10 lines, OPTIMAL | passed | none | 2/2 | pass |

## Agent behaviour

| Scenario | Run | Extraction | Asked | Flagged | Explainer | Session | Cost |
|---|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | 1 | 4/4 | — | — | llm, llm, llm | 363.4 s | ₹8.28, 27 calls |
| amend-budget-cut-christmas-2025 | 1 | 4/4 | — | — | llm, llm | 250.2 s | ₹5.10, 15 calls |
| cannibal-bakery-diwali-2026 | 1 | 4/4 | — | — | llm | 66.6 s | ₹2.28, 9 calls |
| cannibal-frozen-christmas-2025 | 1 | 4/4 | — | — | llm | 124.7 s | ₹4.92, 18 calls |
| cannibal-personal-care-offseason | 1 | 4/4 | — | — | llm | 408.5 s | ₹3.99, 13 calls |
| christmas-2025-bakery-beverages | 1 | 4/4 | — | — | llm | 266.6 s | ₹3.17, 10 calls |
| christmas-2026-frozen-snacks | 1 | 4/4 | — | — | llm | 317.5 s | ₹5.49, 18 calls |
| clear-curd-diwali-2025 | 1 | 5/5 | — | — | llm | 173.4 s | ₹2.90, 8 calls |
| clear-dishwash-offseason | 1 | 5/5 | — | — | llm | 337.6 s | ₹5.04, 15 calls |
| clear-juices-christmas-2025 | 1 | 5/5 | — | — | llm | 146.4 s | ₹1.73, 5 calls |
| clear-shampoo-diwali-2026 | 1 | 6/6 | — | — | llm | 675.5 s | ₹5.38, 19 calls |
| conflict-margin-below-floor | 1 | 5/5 | — | min_margin | llm | 157.4 s | ₹4.45, 18 calls |
| demo-budget-cut-drop-west | 1 | 5/5 | — | target_segment | llm, llm, llm | 183.0 s | ₹10.73, 25 calls |
| diwali-2025-home-personal-care | 1 | 4/4 | — | — | llm | 307.3 s | ₹1.11, 5 calls |
| diwali-2025-snacks-beverages-east-cap | 1 | 5/5 | — | — | llm | 867.6 s | ₹8.29, 19 calls |
| diwali-2026-staples-dairy-margin | 1 | 5/5 | — | target_segment | llm | 38.9 s | ₹1.41, 5 calls |
| diwali-no-budget | 1 | 4/4 | marketing_budget | — | llm | 170.4 s | ₹3.65, 10 calls |
| diwali-snacks-beverages | 1 | 4/4 | — | — | llm | 160.5 s | ₹3.55, 9 calls |
| durga-puja-2025-east | 1 | 4/4 | — | — | llm | 151.2 s | ₹4.98, 18 calls |
| infeasible-clearance-high-margin | 1 | 6/6 | — | — | llm | 69.4 s | ₹3.40, 10 calls |
| infeasible-clearance-tiny-budget | 1 | 5/5 | — | — | llm | 50.4 s | ₹3.80, 11 calls |
| lohri-2026-north | 1 | 4/4 | — | — | llm | 57.0 s | ₹1.71, 5 calls |
| pongal-2026-south | 1 | 4/4 | — | — | llm | 36.7 s | ₹1.42, 5 calls |
| price-war-bakery-beverages-offseason | 1 | 5/5 | — | — | llm | 95.8 s | ₹2.58, 9 calls |
| price-war-home-care-diwali-2025 | 1 | 5/5 | — | — | llm | 69.5 s | ₹1.71, 5 calls |
| price-war-home-care-staples-diwali-2026 | 1 | 6/6 | — | — | llm | 89.6 s | ₹1.95, 5 calls |
| price-war-staples-christmas-2025 | 1 | 6/6 | — | — | llm | 19.7 s | ₹1.14, 5 calls |
| tight-christmas-2025-bakery | 1 | 4/4 | — | — | llm | 42.5 s | ₹2.13, 9 calls |
| tight-diwali-2025-snacks | 1 | 4/4 | — | — | llm | 71.6 s | ₹2.60, 9 calls |
| tight-diwali-2026-personal-care | 1 | 5/5 | — | — | llm | 189.7 s | ₹2.46, 9 calls |
| tight-offseason-beverages | 1 | 4/4 | — | — | llm | 134.2 s | ₹1.08, 5 calls |
| vague-no-category | 1 | 4/4 | scope.categories | — | llm | 69.7 s | ₹2.50, 10 calls |

## Plan quality

Oracle objective (incremental profit plus clearance value) of each scored plan, the rule-based baseline and the best plan for its final request.

| Scenario | Run | Ours | Rule-based | Best | Regret | Against the baseline |
|---|---|---|---|---|---|---|
| amend-add-region-extend-offseason | 1 | ₹131,994 | ₹4,446 (1 of 10 sellers kept) | ₹142,193 (OPTIMAL, 20 lines) | 7.2% | beats |
| amend-budget-cut-christmas-2025 | 1 | ₹72,008 | ₹-34,729 (1 of 10 sellers kept) | ₹94,383 (OPTIMAL, 29 lines) | 23.7% | beats |
| cannibal-bakery-diwali-2026 | 1 | ₹6,025 | ₹-22,845 (2 of 10 sellers kept) | ₹20,582 (OPTIMAL, 10 lines) | 70.7% | beats |
| cannibal-frozen-christmas-2025 | 1 | ₹95,796 | ₹-47,453 (2 of 10 sellers kept) | ₹103,287 (OPTIMAL, 17 lines) | 7.3% | beats |
| cannibal-personal-care-offseason | 1 | ₹97,341 | ₹-37,831 (4 of 10 sellers kept) | ₹8,280 (FEASIBLE, 13 lines) | -1075.6% | beats |
| christmas-2025-bakery-beverages | 1 | ₹54,266 | ₹-85,841 (4 of 10 sellers kept) | ₹92,604 (OPTIMAL, 27 lines) | 41.4% | beats |
| christmas-2026-frozen-snacks | 1 | ₹143,692 | ₹-64,745 (6 of 10 sellers kept) | ₹143,821 (OPTIMAL, 28 lines) | 0.1% | beats |
| clear-curd-diwali-2025 | 1 | ₹-2,816 | ₹-54,844 (1 of 10 sellers kept) | ₹-1,079 (FEASIBLE, 14 lines) | 100.0% | beats |
| clear-dishwash-offseason | 1 | ₹32,104 | ₹4,446 (1 of 10 sellers kept) | ₹51,998 (OPTIMAL, 7 lines) | 38.3% | beats |
| clear-juices-christmas-2025 | 1 | ₹51,155 | ₹-51,800 (3 of 10 sellers kept) | ₹70,088 (OPTIMAL, 20 lines) | 27.0% | beats |
| clear-shampoo-diwali-2026 | 1 | ₹112,578 | ₹-30,597 (2 of 10 sellers kept) | ₹92,556 (FEASIBLE, 20 lines) | -21.6% | beats |
| conflict-margin-below-floor | 1 | ₹14,683 | ₹-24,700 (8 of 10 sellers kept) | ₹22,302 (OPTIMAL, 7 lines) | 34.2% | beats |
| diwali-2025-home-personal-care | 1 | ₹0 | ₹0 (0 of 10 sellers kept) | ₹0 (FEASIBLE, 0 lines) | 0.0% | ties |
| diwali-2025-snacks-beverages-east-cap | 1 | ₹244,714 | ₹-110,036 (2 of 10 sellers kept) | ₹331,599 (OPTIMAL, 68 lines) | 26.2% | beats |
| diwali-2026-staples-dairy-margin | 1 | ₹29,568 | ₹-26,836 (1 of 10 sellers kept) | ₹103,721 (OPTIMAL, 14 lines) | 71.5% | beats |
| diwali-no-budget | 1 | ₹143,183 | ₹-63,025 (5 of 10 sellers kept) | ₹157,803 (OPTIMAL, 35 lines) | 9.3% | beats |
| diwali-snacks-beverages | 1 | ₹143,183 | ₹-63,025 (5 of 10 sellers kept) | ₹157,803 (OPTIMAL, 35 lines) | 9.3% | beats |
| durga-puja-2025-east | 1 | ₹75,235 | ₹-32,446 (4 of 10 sellers kept) | ₹98,396 (OPTIMAL, 15 lines) | 23.5% | beats |
| lohri-2026-north | 1 | ₹56,596 | ₹-46,815 (7 of 10 sellers kept) | ₹71,758 (OPTIMAL, 20 lines) | 21.1% | beats |
| pongal-2026-south | 1 | ₹27,364 | ₹0 (0 of 10 sellers kept) | ₹29,913 (OPTIMAL, 9 lines) | 8.5% | beats |
| price-war-bakery-beverages-offseason | 1 | ₹34,186 | ₹-54,464 (5 of 10 sellers kept) | ₹44,141 (OPTIMAL, 14 lines) | 22.6% | beats |
| price-war-home-care-diwali-2025 | 1 | ₹206,271 | ₹-85,621 (1 of 10 sellers kept) | ₹193,826 (OPTIMAL, 20 lines) | -6.4% | beats |
| price-war-home-care-staples-diwali-2026 | 1 | ₹215,349 | ₹-122,041 (2 of 10 sellers kept) | ₹196,771 (OPTIMAL, 27 lines) | -9.4% | beats |
| price-war-staples-christmas-2025 | 1 | ₹-2,214 | ₹-34,872 (2 of 10 sellers kept) | ₹1,575 (OPTIMAL, 1 lines) | 240.6% | beats |
| tight-christmas-2025-bakery | 1 | ₹3,012 | ₹0 (0 of 10 sellers kept) | ₹9,978 (OPTIMAL, 5 lines) | 69.8% | beats |
| tight-diwali-2025-snacks | 1 | ₹12,555 | ₹-8,916 (2 of 10 sellers kept) | ₹44,223 (OPTIMAL, 11 lines) | 71.6% | beats |
| tight-diwali-2026-personal-care | 1 | ₹73,088 | ₹6,541 (1 of 10 sellers kept) | ₹9,073 (FEASIBLE, 4 lines) | -705.6% | beats |
| tight-offseason-beverages | 1 | ₹0 | ₹0 (0 of 10 sellers kept) | ₹59,577 (OPTIMAL, 10 lines) | 100.0% | ties |
| vague-no-category | 1 | ₹23,440 | ₹-33,040 (4 of 10 sellers kept) | ₹30,968 (OPTIMAL, 10 lines) | 24.3% | beats |

Consistency needs at least two runs per scenario (`make eval RUNS=5`). Under the replay provider a scenario's runs are identical: only a live LLM varies them.

## Failures

- **cannibal-bakery-diwali-2026** run 1: expected `no_strong_substitutes_together: true`: revision 1 promotes SKU0194 and SKU0195 (θ 0.64) together in North, West
- **cannibal-personal-care-offseason** run 1: expected `no_strong_substitutes_together: true`: revision 1 promotes SKU0085 and SKU0087 (θ 0.73) together in North; SKU0077 and SKU0078 (θ 0.69) together in North
- **clear-curd-diwali-2025** run 1: SKU0057 in North is expected to sell through 28.3% of its stock, below the clearance target 50.0%: short by 867 units
- **clear-curd-diwali-2025** run 1: expected `meets_clearance: SKU0057`: North reaches 28.26% of a 50% target, 867 units short
- **demo-budget-cut-drop-west** run 1: expected `meets_clearance: SKU0006`: North reaches 59.87% of a 60% target, 1 units short
