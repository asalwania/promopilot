# PromoPilot eval report

Generated 2026-10-01T18:03:12.256560+00:00 with the `openai` provider on the seed-42 world: 5 scenarios, 5 run(s) each, 25 sessions.

## Metrics

| Metric | Value | Target | Result |
|---|---|---|---|
| Constraint satisfaction | 100.0% (20 of 20) | ≥ 100% | pass |
| Oracle breach rate | 0.0% (0 of 20) | ≤ 15% | pass |
| Open issues per plan (median) | 3 (25 of 25) | report | — |
| Extraction accuracy | 100.0% (115 of 115) | ≥ 95% | pass |
| Clarification behaviour | 100.0% (5 of 5) | ≥ 100% | pass |
| Infeasibility handling | 100.0% (5 of 5) | ≥ 100% | pass |
| Grounding | 100.0% (30 of 30) | ≥ 98% | pass |
| P50 session time | 101.6 s (25 of 25) | report | — |
| P50 session cost | ₹4.17 (25 of 25) | report | — |
| Elasticity recovery (median abs % error) | 8.1% (679 of 800) | ≤ 20% | pass |
| Substitute precision | 86.7% (91 of 105) | ≥ 80% | pass |
| Substitute recall | 100.0% (91 of 91) | ≥ 70% | pass |
| Complement precision | 100.0% (39 of 39) | ≥ 80% | pass |
| Complement recall | 97.5% (39 of 40) | ≥ 70% | pass |
| Baseline WAPE, store x SKU x segment | 43.5% | report (aim ≤ 25%) | — |
| Baseline WAPE, store x SKU | 25.1% | report (aim ≤ 25%) | — |
| Baseline WAPE, region x SKU | 13.5% | report (aim ≤ 25%) | — |
| Plan quality (beats the rule-based baseline) | 100.0% (4 of 4) | ≥ 90% | pass |
| Regret (median, against the best plan) | 8.8% (10 of 20) | ≤ 10% | pass |
| Consistency (Jaccard of selected SKUs across runs) | 100.0% (5 of 5) | ≥ 90% | pass |

- Constraint satisfaction: failed 0, infeasible 5, no_plan 0
- Oracle breach rate: promo_cost_over_budget 0, margin_below_minimum 0, demand_over_stock 0
- Open issues per plan (median): total 55, OVER_CONCENTRATION 5, HEAVY_CANNIBALISATION 35, CLEARANCE_TARGET 15
- Clarification behaviour: asked 5, flagged_only 0, neither 0, unneeded_asks 0
- Infeasibility handling: not_declared 0, no_relaxation 0, nothing_binds 0, no_plan 0
- Grounding: llm 30, ungrounded 0, invalid_answer 0, llm_unavailable 0
- P50 session time: max_s 287, llm_p50_s 53
- P50 session cost: calls 383, input_tokens 3216007, output_tokens 68258, unpriced_runs 0
- Plan quality (beats the rule-based baseline): beats 4, ties 0, loses 0
- Regret (median, against the best plan): best_infeasible 0, best_timed_out 0, largest_model_error 10, largest_planner 0, largest_timeouts 0

## Scenarios

| Scenario | Group | Run | Outcome | Plan | Constraints | Oracle breaches | Properties | Result |
|---|---|---|---|---|---|---|---|---|
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 1 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 2 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 3 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 4 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| amend-budget-cut-christmas-2025 | mid_plan_amendments | 5 | planned | rev 2: 26 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 1 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 2 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 3 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 4 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-no-budget | vague_or_conflicting | 5 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 1 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 2 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 3 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 4 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| diwali-snacks-beverages | standard_festive | 5 | planned | rev 1: 34 lines, OPTIMAL | passed | none | 2/2 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 1 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 2 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 3 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 4 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| infeasible-clearance-high-margin | infeasible_constraints | 5 | planned | rev 1: 0 lines, INFEASIBLE | infeasible | — | 2/2 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 1 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 2 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 3 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 4 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |
| price-war-bakery-beverages-offseason | competitor_price_war | 5 | planned | rev 1: 13 lines, OPTIMAL | passed | none | 2/2 | pass |

## Agent behaviour

| Scenario | Run | Extraction | Asked | Flagged | Explainer | Session | Cost |
|---|---|---|---|---|---|---|---|
| amend-budget-cut-christmas-2025 | 1 | 4/4 | — | — | llm, llm | 137.0 s (LLM 93.3 s) | ₹10.45, 29 calls |
| amend-budget-cut-christmas-2025 | 2 | 4/4 | — | — | llm, llm | 287.4 s (LLM 159.0 s) | ₹11.92, 34 calls |
| amend-budget-cut-christmas-2025 | 3 | 4/4 | — | — | llm, llm | 159.5 s (LLM 85.8 s) | ₹8.42, 24 calls |
| amend-budget-cut-christmas-2025 | 4 | 4/4 | — | — | llm, llm | 200.7 s (LLM 113.5 s) | ₹11.85, 34 calls |
| amend-budget-cut-christmas-2025 | 5 | 4/4 | — | — | llm, llm | 256.0 s (LLM 131.6 s) | ₹15.65, 45 calls |
| diwali-no-budget | 1 | 4/4 | marketing_budget | — | llm | 107.1 s (LLM 58.2 s) | ₹4.24, 12 calls |
| diwali-no-budget | 2 | 4/4 | marketing_budget | — | llm | 88.3 s (LLM 47.1 s) | ₹4.26, 12 calls |
| diwali-no-budget | 3 | 4/4 | marketing_budget | — | llm | 106.7 s (LLM 65.5 s) | ₹4.26, 12 calls |
| diwali-no-budget | 4 | 4/4 | marketing_budget | — | llm | 116.3 s (LLM 75.4 s) | ₹4.23, 12 calls |
| diwali-no-budget | 5 | 4/4 | marketing_budget | — | llm | 101.6 s (LLM 55.5 s) | ₹4.25, 12 calls |
| diwali-snacks-beverages | 1 | 4/4 | — | — | llm | 94.1 s (LLM 42.3 s) | ₹3.90, 10 calls |
| diwali-snacks-beverages | 2 | 4/4 | — | — | llm | 127.0 s (LLM 60.4 s) | ₹7.41, 21 calls |
| diwali-snacks-beverages | 3 | 4/4 | — | — | llm | 93.5 s (LLM 43.4 s) | ₹4.17, 11 calls |
| diwali-snacks-beverages | 4 | 4/4 | — | — | llm | 111.0 s (LLM 44.1 s) | ₹4.15, 11 calls |
| diwali-snacks-beverages | 5 | 4/4 | — | — | llm | 119.4 s (LLM 44.4 s) | ₹4.19, 11 calls |
| infeasible-clearance-high-margin | 1 | 6/6 | — | — | llm | 108.0 s (LLM 29.9 s) | ₹3.63, 10 calls |
| infeasible-clearance-high-margin | 2 | 6/6 | — | — | llm | 69.4 s (LLM 22.6 s) | ₹3.12, 9 calls |
| infeasible-clearance-high-margin | 3 | 6/6 | — | — | llm | 61.5 s (LLM 20.2 s) | ₹3.02, 8 calls |
| infeasible-clearance-high-margin | 4 | 6/6 | — | — | llm | 60.0 s (LLM 20.5 s) | ₹3.02, 8 calls |
| infeasible-clearance-high-margin | 5 | 6/6 | — | — | llm | 68.3 s (LLM 23.9 s) | ₹2.98, 8 calls |
| price-war-bakery-beverages-offseason | 1 | 5/5 | — | — | llm | 47.4 s (LLM 27.1 s) | ₹2.96, 10 calls |
| price-war-bakery-beverages-offseason | 2 | 5/5 | — | — | llm | 73.9 s (LLM 56.0 s) | ₹2.98, 10 calls |
| price-war-bakery-beverages-offseason | 3 | 5/5 | — | — | llm | 73.1 s (LLM 54.7 s) | ₹2.97, 10 calls |
| price-war-bakery-beverages-offseason | 4 | 5/5 | — | — | llm | 70.2 s (LLM 52.6 s) | ₹2.96, 10 calls |
| price-war-bakery-beverages-offseason | 5 | 5/5 | — | — | llm | 59.2 s (LLM 42.2 s) | ₹2.97, 10 calls |

## Plan quality

Oracle objective (incremental profit plus clearance value) of each scored plan, the rule-based baseline, the default sequence's plan and the best plan for its final request. Regret splits into model error (best - default) / best, the planner's choices (default - ours) / best, and timeouts, a part whose plans include one the solver stopped as FEASIBLE.

| Scenario | Run | Ours | Rule-based | Default sequence | Best | Regret | Model error | Planner | Timeouts | Against the baseline |
|---|---|---|---|---|---|---|---|---|---|---|
| amend-budget-cut-christmas-2025 | 1 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| amend-budget-cut-christmas-2025 | 2 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| amend-budget-cut-christmas-2025 | 3 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| amend-budget-cut-christmas-2025 | 4 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| amend-budget-cut-christmas-2025 | 5 | ₹66,466 | ₹-34,729 (1 of 10 sellers kept) | ₹66,466 (OPTIMAL, 26 lines) | ₹81,021 (OPTIMAL, 27 lines) | 18.0% | 18.0% | 0.0% | 0.0% | beats |
| diwali-no-budget | 1 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-no-budget | 2 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-no-budget | 3 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-no-budget | 4 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-no-budget | 5 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 1 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 2 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 3 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 4 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| diwali-snacks-beverages | 5 | ₹146,718 | ₹-63,025 (5 of 10 sellers kept) | ₹146,718 (OPTIMAL, 34 lines) | ₹150,783 (OPTIMAL, 34 lines) | 2.7% | 2.7% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 1 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 2 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 3 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 4 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |
| price-war-bakery-beverages-offseason | 5 | ₹36,039 | ₹-54,464 (5 of 10 sellers kept) | ₹36,039 (OPTIMAL, 13 lines) | ₹42,331 (OPTIMAL, 14 lines) | 14.9% | 14.9% | 0.0% | 0.0% | beats |

Regret by cause over the 20 counted runs (median, then ₹ in all): model error 8.8% (₹144,883), planner 0.0% (₹0), timeouts 0.0% (₹0).

- amend-budget-cut-christmas-2025: consistency 100.0%
- diwali-no-budget: consistency 100.0%
- diwali-snacks-beverages: consistency 100.0%
- infeasible-clearance-high-margin: consistency 100.0%
- price-war-bakery-beverages-offseason: consistency 100.0%

## Failures

None.
