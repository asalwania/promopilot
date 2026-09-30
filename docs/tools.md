# PromoPilot tools

The deterministic tools the planner agent is offered (SPEC §9.6), in the order it is offered them. Every number an agent uses comes from one of them (ADR 0002). Each tool's description and schemas below are exactly what the LLM is shown; its dependencies, company policy and as-of week are bound when the tool is built, never set by the LLM (ADR 0025, ADR 0032). How they fit together is in [the architecture document](architecture.md#tool-contracts).

Generated from the tool registry by `make tool-docs` (`make api-types` runs it too). Do not edit it by hand: change the tool, run `make tool-docs` and commit the result. `make test` fails when this page drifts from the registry ([ADR 0088](adr/0088-readme-for-judges-and-docs-checked-against-code.md)).

## Errors

A call never raises for a bad call: it returns `{"ok": true, "output": ...}` or `{"ok": false, "code", "message", "details"}`, which the planner hands back to the LLM. The codes:

| Code | Meaning |
| --- | --- |
| `unknown_tool` | No tool has that name. |
| `invalid_input` | The arguments break the input schema, an undeclared key included, at any depth (ADR 0079). `details` lists each problem. |
| `model_unavailable` | No trained model the tool can use is registered. |
| `data_unavailable` | No data is loaded for the as-of week. |
| `tool_failed` | The tool kept raising after the planner's retries (ADR 0049). |
| `timeout` | The call ran longer than `TOOL_TIMEOUT_SECONDS` (ADR 0071). |

## Tools

| Tool | Summary |
| --- | --- |
| [`estimate_demand`](#estimate_demand) | Predict what each promo option would do if it ran alone: units sold in its region over the promo weeks (mean and standard deviation), the no-promotion baseline, the pull-forward dip in the four weeks after, incremental units net of that dip, revenue, gross profit, margin, promo cost and incremental profit in rupees, plus units per customer segment. |
| [`get_scope_data`](#get_scope_data) | List the regions (with their stores and cities) and the product hierarchy (category, subcategory, SKU with name, brand, pack size, base price and unit cost in rupees, and whether it is a KVI) that a plan may cover. |
| [`get_inventory_status`](#get_inventory_status) | Stock per SKU and region at the as-of week, pooled over the region's stores: units on hand, safety stock, units on order, available stock (on hand minus safety stock, the most a promotion may sell), days of cover, and whether the SKU is overstocked there (days of cover above the company-policy threshold). |
| [`get_holidays`](#get_holidays) | List the holidays per region and week in a window of weeks after the as-of week: the holiday's name, the week's start date, its intensity (0 to 1: the festival week at the festival's full strength, the week before it at a lower lead-in level) and whether it is national (celebrated in every region) or regional. |
| [`get_competitor_gaps`](#get_competitor_gaps) | Compare our base prices with the competitor's latest prices before the as-of week, per SKU and region, widest gap first. |
| [`get_relations`](#get_relations) | List the detected substitutes and complements of each SKU. |
| [`generate_candidates`](#generate_candidates) | Generate every promo option for the planning request: each in-scope SKU and region, mechanism, depth, duration, start week inside the promo window, and target segment (one segment or All customers); a BUNDLE pairs a SKU with a detected complement. |
| [`run_optimizer`](#run_optimizer) | Select the promo plan from a candidate set made by generate_candidates: at most one plan line per SKU per region (a BUNDLE's partner included), maximising incremental profit net of cannibalisation (including what two substitutes lose when promoted together) plus halo and clearance value. |
| [`relax_constraints`](#relax_constraints) | For a candidate set made by generate_candidates, say whether its request is feasible and, if no plan can reach every clearance target within the request's other constraints, the smallest change to the request's own constraints that makes it feasible: a higher marketing budget or regional budget cap, a lower minimum margin (never below the company-policy margin floor), a looser promoted-SKU cap (never above policy's), the KVI price tolerance turned off (only when the request turned it on), or a lower or dropped clearance target. |
| [`compare_mechanisms`](#compare_mechanisms) | Compare promotion mechanisms (PCT_OFF, BOGO, FIXED_PRICE, and BUNDLE when the SKU has a detected complement) for one SKU in one region of the planning request. |
| [`simulate_plan`](#simulate_plan) | Simulate a promo plan many times (Monte Carlo): each run samples the demand model's elasticities, mechanism effects and other terms within their uncertainty, then weekly demand noise per store and segment. |

### `estimate_demand`

Predict what each promo option would do if it ran alone: units sold in its region over the promo weeks (mean and standard deviation), the no-promotion baseline, the pull-forward dip in the four weeks after, incremental units net of that dip, revenue, gross profit, margin, promo cost and incremental profit in rupees, plus units per customer segment. Options must start on or after the model's as-of week. Competitor prices default to the last ones known; override them per region and SKU to test a competitor move. Cannibalisation and halo on other SKUs are not included.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `options` | array of [PlanLine](#planline) | yes | minItems 1, maxItems 200 |  |
| `competitor_prices` | array of [CompetitorPrice](#competitorprice) | no |  | Competitor price overrides over the promo; others are the last known. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `model` | [ModelVersion](#modelversion) | yes |  |  |
| `estimates` | array of [OptionEstimate](#optionestimate) | yes |  |  |

### `get_scope_data`

List the regions (with their stores and cities) and the product hierarchy (category, subcategory, SKU with name, brand, pack size, base price and unit cost in rupees, and whether it is a KVI) that a plan may cover. Filter by regions, categories or SKU ids; omit a filter to list everything.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [Region](#region) or null | no | default `null` | Omit for every region. |
| `categories` | array of string or null | no | default `null` | Omit for every category. |
| `sku_ids` | array of string or null | no | default `null` | Omit for every SKU. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [RegionScope](#regionscope) | yes |  |  |
| `categories` | array of [CategoryScope](#categoryscope) | yes |  |  |

### `get_inventory_status`

Stock per SKU and region at the as-of week, pooled over the region's stores: units on hand, safety stock, units on order, available stock (on hand minus safety stock, the most a promotion may sell), days of cover, and whether the SKU is overstocked there (days of cover above the company-policy threshold). Filter by regions, categories or SKU ids, or list only overstocked SKUs.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [Region](#region) or null | no | default `null` | Omit for every region. |
| `categories` | array of string or null | no | default `null` | Omit for every category. |
| `sku_ids` | array of string or null | no | default `null` | Omit for every SKU. |
| `overstocked_only` | boolean | no | default `false` | List only overstocked SKUs. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `snapshot_week` | integer | yes |  | The stock is as at the end of this week. |
| `overstock_threshold_days` | number | yes |  |  |
| `statuses` | array of [InventoryStatus](#inventorystatus) | yes |  |  |

### `get_holidays`

List the holidays per region and week in a window of weeks after the as-of week: the holiday's name, the week's start date, its intensity (0 to 1: the festival week at the festival's full strength, the week before it at a lower lead-in level) and whether it is national (celebrated in every region) or regional.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [Region](#region) or null | no | default `null` | Omit for every region. |
| `start_week` | integer | yes | minimum 0 | First week id of the window, after the as-of week. |
| `end_week` | integer | yes | minimum 0 | Last week id of the window, inclusive. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `holidays` | array of [HolidayWeek](#holidayweek) | yes |  |  |

### `get_competitor_gaps`

Compare our base prices with the competitor's latest prices before the as-of week, per SKU and region, widest gap first. cpi is competitor price ÷ our base price; gap is 1 minus cpi, positive when the competitor is cheaper. undercut marks a KVI whose cpi is below 1 minus the company-policy undercut threshold. Filter by regions, categories, SKU ids or KVIs only; omit a filter to include everything.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [Region](#region) or null | no | minItems 1, default `null` |  |
| `categories` | array of string or null | no | minItems 1, default `null` |  |
| `sku_ids` | array of string or null | no | minItems 1, default `null` |  |
| `kvi_only` | boolean | no | default `false` |  |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes | minimum 0 |  |
| `undercut_threshold` | number | yes |  |  |
| `kvi_price_tolerance` | number | yes |  | How far above the competitor a KVI promo price may sit, when enabled. |
| `gaps` | array of [CompetitorGap](#competitorgap) | yes |  |  |

### `get_relations`

List the detected substitutes and complements of each SKU. A substitute is a SKU in the same subcategory whose sales fall when this SKU's price is cut (cannibalisation): theta is the cross-price effect, with its standard error and Benjamini-Hochberg q-value, strongest first. A complement is a SKU bought with this one far more often than chance (halo): lift and support come from baskets, and theta, negative, is the cross-price effect where it could be estimated (null otherwise), highest lift first. Relations hold in every region.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_ids` | array of string | yes | minItems 1, maxItems 50 |  |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `model` | [ModelVersion](#modelversion) | yes |  |  |
| `relations` | array of [SkuRelations](#skurelations) | yes |  |  |

### `generate_candidates`

Generate every promo option for the planning request: each in-scope SKU and region, mechanism, depth, duration, start week inside the promo window, and target segment (one segment or All customers); a BUNDLE pairs a SKU with a detected complement. Options deeper than the company-policy maximum discount, below unit cost (unless overstocked), or whose P90 units exceed available stock are pruned. The rest are predicted, with cannibalisation, halo and clearance value. A KVI the competitor undercuts also gets a price-match option: PCT_OFF at the smallest whole-percent depth that reaches the competitor's price. SKUs the request names for clearance count as overstocked. Returns counts, pruned counts per reason, counts per region and mechanism, the price matches offered, the top options by value, and a candidate_set_id to pass to the optimiser. Narrow by mechanisms, target segments or SKU ids to generate fewer, or leave SKUs out with exclude_sku_ids.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `request` | [PlanningRequest](#planningrequest) | yes |  |  |
| `mechanisms` | array of [Mechanism](#mechanism) or null | no | default `null` | Omit for all four. |
| `target_segments` | array of [TargetSegment](#targetsegment) or null | no | default `null` | Omit for every segment and All customers. |
| `sku_ids` | array of string or null | no | default `null` | Only these SKUs of the request's scope; omit for all. |
| `exclude_sku_ids` | array of string or null | no | default `null` | SKUs of the request's scope to leave out, in every region: the lever for a SKU the Critic flags. Not a clearance target of the brief; omit to leave none out. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `candidate_set_id` | string (uuid) | yes |  |  |
| `demand_model` | [ModelVersion](#modelversion) | yes |  |  |
| `relations_model` | [ModelVersion](#modelversion) | yes |  |  |
| `as_of_week` | integer | yes |  |  |
| `enumerated` | integer | yes |  |  |
| `kept` | integer | yes |  |  |
| `pruned` | array of [PrunedCount](#prunedcount) | yes |  |  |
| `by_region_and_mechanism` | array of [RegionMechanismCount](#regionmechanismcount) | yes |  |  |
| `price_matches` | array of [PriceMatchOffer](#pricematchoffer) | yes |  | Undercut KVIs in scope and the depth that matches the competitor's price. |
| `top` | array of [CandidateOption](#candidateoption) | yes |  | Up to 20 options, best value first. |

### `run_optimizer`

Select the promo plan from a candidate set made by generate_candidates: at most one plan line per SKU per region (a BUNDLE's partner included), maximising incremental profit net of cannibalisation (including what two substitutes lose when promoted together) plus halo and clearance value. The plan keeps total promo cost within the marketing budget, the blended margin at or above the minimum margin (never below the company-policy margin floor), and at most the company-policy number of promoted SKUs per category per region; the request may tighten that cap, cap the promo cost per region, and turn on the KVI price tolerance. Only options that pay for themselves alone are selected, or that sell a SKU the request names for clearance towards its target. Each clearance target is met when any plan can meet it; otherwise the plan comes as close as it can, the shortfall is reported, the status is INFEASIBLE and the smallest relaxation of the request's constraints is attached (see relax_constraints). Returns the solver status (OPTIMAL, FEASIBLE when the time limit ran out first, INFEASIBLE when no plan reaches every clearance target), the objective, each selected plan line with its numbers and why it was chosen, the plan's totals, the binding constraints (those whose removal would raise the objective; for an infeasible request, those that make it infeasible), the best options left out with the rules they break, clearance shortfalls, the relaxation, and any request value that would have loosened company policy (policy was kept). A candidate_set_id that is no longer stored must be regenerated.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `candidate_set_id` | string (uuid) | yes |  | From generate_candidates. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `candidate_set_id` | string (uuid) | yes |  |  |
| `status` | [SolveStatus](#solvestatus) | yes |  |  |
| `objective` | number | yes |  | The lines' values less what selected substitute pairs lose together. |
| `lines` | array of [OptimizedLine](#optimizedline) | yes |  |  |
| `total_promo_cost` | number | yes |  |  |
| `marketing_budget` | number | yes |  |  |
| `blended_margin` | number or null | yes |  | None when no line is selected. |
| `min_margin` | number | yes |  | The minimum margin applied: the request's, never below the margin floor. |
| `pairwise_cannibalisation` | number | yes |  | What the selected substitute pairs lose together (negative: they gain). |
| `candidate_options` | integer | yes |  |  |
| `eligible_options` | integer | yes |  | Candidate options that pay for themselves alone and keep every per-line rule. |
| `pairs` | integer | yes |  | Pairs of eligible options that interact. |
| `binding_constraints` | array of [BindingConstraint](#bindingconstraint) | yes |  | Constraints whose removal gives a strictly better objective (OPTIMAL only). |
| `not_selected` | array of [NotSelectedOption](#notselectedoption) | yes |  | The best option of up to 5 SKUs and regions with no plan line, best first. |
| `clearance_shortfalls` | array of [ClearanceShortfall](#clearanceshortfall) | yes |  | Clearance targets no plan reaches, and by how much this plan misses them. |
| `policy_findings` | array of [PolicyFinding](#policyfinding) | yes |  | Request values that would have loosened company policy; policy was kept. |
| `relaxation` | [Relaxation](#relaxation) or null | yes |  | When no plan reaches every clearance target, the smallest change to the request's constraints that makes it feasible; null otherwise. |

### `relax_constraints`

For a candidate set made by generate_candidates, say whether its request is feasible and, if no plan can reach every clearance target within the request's other constraints, the smallest change to the request's own constraints that makes it feasible: a higher marketing budget or regional budget cap, a lower minimum margin (never below the company-policy margin floor), a looser promoted-SKU cap (never above policy's), the KVI price tolerance turned off (only when the request turned it on), or a lower or dropped clearance target. The change is the least sum of each change as a share of the request's value. Company policy is never relaxed: policy_binds says when no change to the budget, caps, margin or tolerance alone would reach the targets, so a target must come down, and policy_allows gives the most sell-through policy allows. Returns the solver status (INFEASIBLE, OPTIMAL, or FEASIBLE when the time limit ran out before either was proven), the relaxation (null when the request is feasible), the constraints that make it infeasible, and the clearance shortfalls of the closest plan. A candidate_set_id that is no longer stored must be regenerated.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `candidate_set_id` | string (uuid) | yes |  | From generate_candidates. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `candidate_set_id` | string (uuid) | yes |  |  |
| `status` | [SolveStatus](#solvestatus) | yes |  |  |
| `relaxation` | [Relaxation](#relaxation) or null | yes |  | The smallest change to the request's constraints that makes it feasible; null when it is feasible. proven is false when time ran out first. |
| `binding_constraints` | array of [BindingConstraint](#bindingconstraint) | yes |  | For an infeasible request: the clearance targets missed and each constraint the relaxation changes, at the request's values. |
| `clearance_shortfalls` | array of [ClearanceShortfall](#clearanceshortfall) | yes |  | Clearance targets the closest plan misses, and by how much. |
| `policy_findings` | array of [PolicyFinding](#policyfinding) | yes |  | Request values that would have loosened company policy; policy was kept. |

### `compare_mechanisms`

Compare promotion mechanisms (PCT_OFF, BOGO, FIXED_PRICE, and BUNDLE when the SKU has a detected complement) for one SKU in one region of the planning request. For each mechanism it finds the option with the highest value (incremental profit - cannibalisation + halo + clearance value) over every depth, duration, start week inside the promo window and target segment that keeps the per-line rules (maximum discount, not below unit cost unless overstocked, P90 units within available stock). Returns, best first, each mechanism's option with its effective price, expected units, revenue, gross profit, margin, promo cost, incremental profit, cannibalisation, halo, clearance value and value; a BUNDLE names its partner and basket lift. A mechanism whose every option breaks a rule is listed last with the rules it breaks.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `request` | [PlanningRequest](#planningrequest) | yes |  |  |
| `sku_id` | string | yes |  | A SKU in the request's scope. |
| `region` | [Region](#region) | yes |  | A region in the request's scope. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `demand_model` | [ModelVersion](#modelversion) | yes |  |  |
| `relations_model` | [ModelVersion](#modelversion) | yes |  |  |
| `as_of_week` | integer | yes |  |  |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `outcomes` | array of [MechanismOutcome](#mechanismoutcome) | yes |  | Mechanisms with an option, highest value first, then those without. |

### `simulate_plan`

Simulate a promo plan many times (Monte Carlo): each run samples the demand model's elasticities, mechanism effects and other terms within their uncertainty, then weekly demand noise per store and segment. Units are capped at each SKU's pooled available stock in the region. Returns P10/P50/P90 of units, revenue, gross profit, margin, sell-through and promo spend for each plan line (over its promo weeks; units and sell-through are the anchor SKU's, money includes a BUNDLE's partner) and for the whole plan, the stock-out probability of each line (the share of runs whose demand reached the available stock) and of each region (at least one of its lines ran out). To stress-test a price war, pass competitor_reaction: in each run, the competitor matches each line's discount with probability match_probability, which removes the promotion's gain on the competitor's price. The seed is fixed, so the same plan and scenario give the same result.

**Input**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `lines` | array of [PlanLine](#planline) | yes | minItems 1, maxItems 200 | The plan's lines: one per SKU per region at most, a BUNDLE partner included. |
| `n_runs` | integer or null | no | minimum 100, maximum 5000, default `null` | Runs to simulate; omit for the default. |
| `competitor_reaction` | [CompetitorReaction](#competitorreaction) or null | no | default `null` | The competitor-reaction scenario; omit for a competitor that never reacts. |

**Output**

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `demand_model` | [ModelVersion](#modelversion) | yes |  |  |
| `as_of_week` | integer | yes |  |  |
| `simulation` | [PlanSimulation](#plansimulation) | yes |  |  |

## Schemas

### BindingConstraint

A constraint that limits the plan: dropping it gives a strictly better objective, or,
when time ran out, one that may.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `kind` | [ConstraintKind](#constraintkind) | yes |  |  |
| `source` | [ConstraintSource](#constraintsource) | yes |  |  |
| `limit` | number | yes |  |  |
| `category` | string or null | no | default `null` |  |
| `region` | [Region](#region) or null | no | default `null` |  |
| `sku_id` | string or null | no | default `null` |  |
| `evidence` | [BindingEvidence](#bindingevidence) | yes |  |  |
| `objective_gain` | number or null | yes |  |  |

### BindingEvidence

How sure the optimiser is that a constraint binds (ADR 0038).

string, one of `exact`, `lower_bound`, `unproven`, `infeasible`.

### CandidateOption

One kept option's headline numbers (rupees, units over its promo weeks).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `option` | [PlanLine](#planline) | yes |  |  |
| `units` | number | yes |  |  |
| `p90_units` | number | yes |  |  |
| `available_stock` | number | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `cannibalised_profit` | number | yes |  |  |
| `halo_profit` | number | yes |  |  |
| `clearance_value` | number | yes |  |  |
| `value` | number | yes |  | incremental_profit - cannibalised_profit + halo_profit + clearance_value |

### CategoryScope

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `category` | string | yes |  |  |
| `subcategories` | array of [SubcategoryScope](#subcategoryscope) | yes |  |  |

### ClearanceShortfall

A clearance target the plan misses: no plan within the other constraints reaches it,
so the optimiser returned the plan that comes closest and reports by how much it falls
short (SPEC §9.4, F-06 AC2, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `target` | number | yes |  |  |
| `expected_sell_through` | number | yes |  |  |
| `shortfall_units` | number | yes |  |  |

### ClearanceTarget

The minimum sell-through the brief asks for a SKU it names for clearance, in every
region of the scope (ADR 0014, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `sell_through` | number | yes | exclusiveMinimum 0, maximum 1 |  |

### CompetitorGap

One SKU in one region against the competitor's latest price before the as-of week.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `sku_id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `category` | string | yes |  |  |
| `subcategory` | string | yes |  |  |
| `is_kvi` | boolean | yes |  |  |
| `base_price` | number | yes |  | Our regular shelf price in rupees. |
| `competitor_price` | number | yes |  | The competitor's latest price in rupees. |
| `competitor_on_promo` | boolean | yes |  | Whether that price was a competitor promo. |
| `price_week` | integer | yes | minimum 0 | The week of that price, before the as-of week. |
| `cpi` | number | yes |  | Competitor price index: competitor price ÷ base price. |
| `gap` | number | yes |  | 1 minus CPI: how much cheaper the competitor is (< 0: dearer). |
| `undercut` | boolean | yes |  | A KVI whose CPI is below 1 minus the undercut threshold. |

### CompetitorPrice

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `sku_id` | string | yes |  |  |
| `price` | number | yes | exclusiveMinimum 0 | The competitor's shelf price in rupees. |

### CompetitorReaction

The competitor-reaction scenario (F-09 AC2, ADR 0045): in each run, each plan line's
competitor matches its discount with this probability, independently of the other lines.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `match_probability` | number | yes | minimum 0, maximum 1 | Chance, per plan line and run, that the competitor matches our discount. |

### Complement

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `lift` | number | yes |  | P(both in a basket) / (P(one) x P(other)). |
| `support` | number | yes |  | Share of baskets holding both SKUs. |
| `theta` | number or null | yes |  | Cross-price effect, or null if not estimable. |
| `std_error` | number or null | yes |  |  |

### ConstraintKind

A plan-level constraint the optimiser enforces (ADR 0036, ADR 0038).

string, one of `marketing_budget`, `minimum_margin`, `margin_floor`, `max_promoted_skus`, `regional_budget`, `clearance_target`, `kvi_price_tolerance`, `strong_substitutes`.

### ConstraintSource

Who set a constraint: only the brief's constraints may be relaxed (ADR 0007).

string, one of `brief`, `company_policy`.

### HolidayWeek

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `holiday` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `week_id` | integer | yes |  |  |
| `week_start` | string (date) | yes |  |  |
| `intensity` | number | yes |  |  |
| `national` | boolean | yes |  |  |

### InventoryStatus

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `on_hand` | integer | yes |  |  |
| `safety_stock` | integer | yes |  |  |
| `on_order` | integer | yes |  |  |
| `available_stock` | integer | yes |  |  |
| `days_of_cover` | number | yes |  |  |
| `is_overstock` | boolean | yes |  |  |

### LineSimulation

One plan line's simulated ranges, identified by its SKU and region.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `units` | [Percentiles](#percentiles) | yes |  |  |
| `revenue` | [Percentiles](#percentiles) | yes |  |  |
| `gross_profit` | [Percentiles](#percentiles) | yes |  |  |
| `margin` | [Percentiles](#percentiles) | yes |  |  |
| `promo_spend` | [Percentiles](#percentiles) | yes |  |  |
| `sell_through` | [Percentiles](#percentiles) or null | yes |  |  |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `stockout_probability` | number | yes | minimum 0, maximum 1 |  |

### Mechanism

string, one of `PCT_OFF`, `BOGO`, `BUNDLE`, `FIXED_PRICE`.

### MechanismOption

One promo option's expected numbers, as its prediction gave them (rupees, units over
its promo weeks; a BUNDLE's money fields include its partner).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `option` | [PlanLine](#planline) | yes |  |  |
| `anchor_sku_id` | string | yes |  |  |
| `partner_sku_id` | string or null | no | default `null` |  |
| `basket_lift` | number or null | no | default `null` |  |
| `effective_price` | number | yes |  |  |
| `partner_effective_price` | number or null | no | default `null` |  |
| `units` | number | yes |  |  |
| `revenue` | number | yes |  |  |
| `gross_profit` | number | yes |  |  |
| `margin` | number | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `cannibalised_profit` | number | yes |  |  |
| `halo_profit` | number | yes |  |  |
| `clearance_value` | number | yes |  |  |
| `value` | number | yes |  |  |

### MechanismOutcome

One mechanism in a comparison: its best option, or why it has none.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `mechanism` | [Mechanism](#mechanism) | yes |  |  |
| `best` | [MechanismOption](#mechanismoption) or null | yes |  |  |
| `chosen` | boolean | no | default `false` |  |
| `unavailable` | array of [PruneReason](#prunereason) | no | default `[]` |  |

### ModelVersion

The registered model that produced the numbers, so a plan can be traced to it.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `model_id` | string (uuid) | yes |  |  |
| `version` | integer | yes |  |  |
| `as_of_week` | integer | yes |  |  |

### NotSelectedOption

The best option of a SKU and region with no plan line, and why it was left out.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `option` | [PlanLine](#planline) | yes |  |  |
| `value` | number | yes |  |  |
| `reasons` | array of [NotSelectedReason](#notselectedreason) | yes |  |  |
| `cannibalises` | array of string | no | default `[]` |  |

### NotSelectedReason

Why a promo option is not in the plan: a rule it breaks alone or added to the plan.

string, one of `low_uplift`, `out_of_stock`, `breaks_policy`, `over_budget`, `over_regional_budget`, `breaks_margin`, `max_promoted_skus`, `misses_clearance_target`, `breaks_kvi_tolerance`, `strong_substitute`, `cannibalises`, `time_limit`.

### OptimizedLine

A selected plan line's numbers, as its promo option predicted them (rupees, units
over its promo weeks).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `option` | [PlanLine](#planline) | yes |  |  |
| `units` | number | yes |  |  |
| `p90_units` | number | yes |  |  |
| `available_stock` | number | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `revenue` | number | yes |  |  |
| `gross_profit` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `cannibalised_profit` | number | yes |  |  |
| `halo_profit` | number | yes |  |  |
| `clearance_value` | number | yes |  |  |
| `value` | number | yes |  | incremental_profit - cannibalised_profit + halo_profit + clearance_value |
| `why_chosen` | [WhyChosen](#whychosen) | yes |  |  |

### OptionEstimate

One option's predicted outcomes, summed over its region (field meanings: ADR 0024).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `option` | [PlanLine](#planline) | yes |  |  |
| `units` | number | yes |  |  |
| `units_std` | number | yes |  |  |
| `baseline_units` | number | yes |  |  |
| `pull_forward_units` | number | yes |  |  |
| `incremental_units` | number | yes |  |  |
| `revenue` | number | yes |  |  |
| `gross_profit` | number | yes |  |  |
| `margin` | number | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `segments` | array of [SegmentEstimate](#segmentestimate) | yes |  |  |

### Percentiles

The 10th, 50th and 90th percentiles of one simulated metric across the runs.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `p10` | number | yes |  |  |
| `p50` | number | yes |  |  |
| `p90` | number | yes |  |  |

### PlanLine

A promo option selected into a promo plan: one (SKU, region) decision (ADR 0004).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `mechanism` | [Mechanism](#mechanism) | yes |  |  |
| `depth_pct` | integer | yes | minimum 1, maximum 100 |  |
| `duration_weeks` | integer | yes | minimum 1, maximum 4 |  |
| `start_week` | integer | yes | minimum 0 |  |
| `target_segment` | [TargetSegment](#targetsegment) | yes |  |  |
| `bundle_partner_sku_id` | string or null | no | default `null` |  |

### PlanSimulation

What `simulate` returns for a promo plan, and what a plan revision stores.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `n_runs` | integer | yes | minimum 1 |  |
| `seed` | integer | yes |  |  |
| `competitor_reaction` | [CompetitorReaction](#competitorreaction) or null | no | default `null` |  |
| `lines` | array of [LineSimulation](#linesimulation) | no | default `[]` |  |
| `total` | [SimulatedOutcomes](#simulatedoutcomes) | yes |  |  |
| `regions` | array of [RegionStockout](#regionstockout) | no | default `[]` |  |

### PlanningRequest

Money is in rupees (ADR 0015). The brief's optional constraints may only tighten
company policy; a value that would loosen it is kept here as read, and planning applies
the policy value instead and flags it (ADR 0007, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes | minimum 0 |  |
| `scope` | [Scope](#scope) | yes |  |  |
| `promo_window` | [PromoWindow](#promowindow) | yes |  |  |
| `marketing_budget` | number | yes | exclusiveMinimum 0 |  |
| `min_margin` | number or null | no | minimum 0, exclusiveMaximum 1, default `null` |  |
| `clearance_targets` | array of [ClearanceTarget](#clearancetarget) | no | default `[]` |  |
| `regional_budget_caps` | map of string to number | no |  |  |
| `kvi_price_tolerance` | number or null | no | minimum 0, exclusiveMaximum 1, default `null` |  |
| `max_promoted_skus_per_category_per_region` | integer or null | no | minimum 1, default `null` |  |

### PolicyFinding

A brief value that would loosen company policy: planning keeps the policy value and
flags it (ADR 0007, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `field` | string | yes |  |  |
| `requested` | number | yes |  |  |
| `applied` | number | yes |  |  |
| `message` | string | yes |  |  |

### PriceMatchOffer

A KVI the competitor undercuts, and the PCT_OFF depth that matches its price.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `depth_pct` | integer | yes |  |  |
| `competitor_price` | number | yes |  |  |

### PromoWindow

The future weeks, inclusive, in which a plan's promotions must start and end.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `start_week` | integer | yes | minimum 0 |  |
| `end_week` | integer | yes | minimum 0 |  |

### PruneReason

Why option generation dropped an enumerated promo option, in the order the rules are
applied (ADR 0035).

string, one of `no_charm_price`, `max_discount`, `below_cost`, `duplicate_price`, `stock`, `partner_stock`.

### PrunedCount

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `reason` | [PruneReason](#prunereason) | yes |  |  |
| `count` | integer | yes |  |  |

### Region

string, one of `North`, `South`, `East`, `West`.

### RegionMechanismCount

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `mechanism` | [Mechanism](#mechanism) | yes |  |  |
| `count` | integer | yes |  |  |

### RegionScope

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `stores` | array of [StoreInfo](#storeinfo) | yes |  |  |

### RegionStockout

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `stockout_probability` | number | yes | minimum 0, maximum 1 |  |

### Relaxation

The smallest change to the brief's constraints that makes an infeasible request
feasible: the least sum of each change as a share of the brief's value (ADR 0044).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `changes` | array of [RelaxedConstraint](#relaxedconstraint) | yes |  |  |
| `policy_binds` | boolean | yes |  |  |
| `proven` | boolean | yes |  |  |

### RelaxedConstraint

One brief constraint the relaxation changes, and by how much (ADR 0044).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `kind` | [ConstraintKind](#constraintkind) | yes |  |  |
| `source` | [ConstraintSource](#constraintsource) | no | default `brief` |  |
| `region` | [Region](#region) or null | no | default `null` |  |
| `sku_id` | string or null | no | default `null` |  |
| `current` | number | yes |  |  |
| `relaxed` | number or null | yes |  |  |
| `change` | number | yes |  |  |
| `policy_allows` | number or null | no | default `null` |  |

### Scope

The regions and categories a planning request covers, optionally narrowed to SKUs.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [Region](#region) | yes | minItems 1 |  |
| `categories` | array of string | yes | minItems 1 |  |
| `sku_ids` | array of string | no | default `[]` |  |

### Segment

A behavioural customer group; never defined by protected attributes.

string, one of `Value Seekers`, `Families`, `Premium`, `Young Urban`.

### SegmentEstimate

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `segment` | [Segment](#segment) | yes |  |  |
| `units` | number | yes |  |  |
| `units_std` | number | yes |  |  |
| `baseline_units` | number | yes |  |  |

### SelectionReason

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `code` | [SelectionReasonCode](#selectionreasoncode) | yes |  |  |
| `amount` | number | yes |  |  |

### SelectionReasonCode

A positive part of a plan line's value (ADR 0005, ADR 0035), or the clearance target it
helps meet (ADR 0040).

string, one of `incremental_profit`, `clearance_value`, `halo`, `clearance_target`.

### SimulatedOutcomes

Ranges over the promo weeks, units capped at pooled available stock (ADR 0004, 0011).

Units and sell-through are the anchor SKU's; revenue, gross profit and promo spend
include a BUNDLE's partner (ADR 0017). Margin is gross profit over revenue in each run
(0 in a run with no revenue). Sell-through is None when there is no available stock.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `units` | [Percentiles](#percentiles) | yes |  |  |
| `revenue` | [Percentiles](#percentiles) | yes |  |  |
| `gross_profit` | [Percentiles](#percentiles) | yes |  |  |
| `margin` | [Percentiles](#percentiles) | yes |  |  |
| `promo_spend` | [Percentiles](#percentiles) | yes |  |  |
| `sell_through` | [Percentiles](#percentiles) or null | yes |  |  |

### SkuInfo

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `brand` | string | yes |  |  |
| `pack_size` | string | yes |  |  |
| `base_price` | number | yes |  |  |
| `unit_cost` | number | yes |  |  |
| `is_kvi` | boolean | yes |  |  |

### SkuRelations

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `substitutes` | array of [Substitute](#substitute) | yes |  |  |
| `complements` | array of [Complement](#complement) | yes |  |  |

### SolveStatus

string, one of `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`.

### StoreInfo

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `store_id` | string | yes |  |  |
| `city` | string | yes |  |  |

### SubcategoryScope

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `subcategory` | string | yes |  |  |
| `skus` | array of [SkuInfo](#skuinfo) | yes |  |  |

### Substitute

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sku_id` | string | yes |  |  |
| `theta` | number | yes |  | Cross-price effect: positive for a substitute. |
| `std_error` | number | yes |  |  |
| `q_value` | number | yes |  |  |

### TargetSegment

Who a plan line is offered to: one segment exclusively, or All customers (ADR 0006).

string, one of `Value Seekers`, `Families`, `Premium`, `Young Urban`, `All customers`.

### WhyChosen

Why a plan line was chosen: the positive parts of its value, what it is worth alone,
and whether it is the best option the optimiser could pick for its SKU and region.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `reasons` | array of [SelectionReason](#selectionreason) | yes |  |  |
| `value` | number | yes |  |  |
| `best_for_sku_region` | boolean | yes |  |  |
