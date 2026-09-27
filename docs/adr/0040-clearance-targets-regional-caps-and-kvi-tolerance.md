# Clearance targets solve in two phases; regional caps, the KVI tolerance and a tighter SKU cap are plan-level constraints; a brief only tightens policy

E6 (#36) makes the optimiser honour the rest of the planning request (SPEC §9.4):

- clearance targets for SKUs the brief names;
- optional regional budget caps;
- the optional KVI price tolerance;
- a promoted-SKU cap tighter than company policy's.

It also adds price-match options for undercut KVIs, and the tighten-only check on company policy (ADR 0007). SPEC, ADR 0014 and ADR 0031 fix what these constraints are. They leave open how the request carries them, how sell-through is computed, what "hard, then soft if infeasible" means in the solver, what a price match is, and where the flags go. We chose these with the owner:

- **The planning request carries the brief's constraints.** `PlanningRequest` gains:
  - `clearance_targets`: a `(sku_id, sell_through)` per SKU, with the sell-through above 0 and at most 1. A SKU has at most one target. It applies separately in every region of the scope. Stock is pooled only within a region (ADR 0004), so clearing North does nothing for West's write-off.
  - `regional_budget_caps`: rupees per region, positive, only for regions in scope.
  - `kvi_price_tolerance`: None leaves company policy's setting (off by default); a number turns the rule on at that tolerance.
  - `max_promoted_skus_per_category_per_region`: an optional tighter cap.

  A clearance target always carries its figure; there is no company-policy default. When a brief names a SKU for clearance without a figure, #46's Context agent asks for one or records an assumption. This keeps ADR 0014's rejection of a policy-wide default target. A target naming a SKU outside the scope is `invalid_input` from `generate_candidates` and a `PlanningError` from a session; it never widens the scope.
- **Reading these fields from a brief is left to #46.** The LLM's `BriefReading` is unchanged. A new field would change the committed cassette's request hash, and re-recording needs a live key. Until #46, the fields reach the optimiser through `generate_candidates` and direct planner calls.
- **A brief only tightens company policy (`guardrails.plan_limits`).** It returns the rules a request is planned under, who set each one, and a `PolicyFinding` for each brief value that would loosen policy:
  - a minimum margin below the margin floor;
  - a promoted-SKU cap above policy's;
  - a KVI tolerance wider than policy's. The rule is still turned on, at policy's tolerance.

  Each finding keeps the brief's value and the value applied. The request itself keeps what the brief said. `solve`, `run_optimizer`, plan validation and the plan revision all read these rules from `plan_limits`, so they cannot disagree. Findings are on `OptimisationResult`, the `run_optimizer` output and the plan revision (migration 0007, JSONB). #46 turns them into flagged assumptions.
- **Sell-through is measured over the promo window, per SKU and region.** It is the expected units sold over the whole promo window ÷ available stock at the as-of week (on hand minus safety stock, the stock the P90 rule uses).
  - Without a plan line, the units are the demand model's own no-promotion forecast over the window. That is `predict`'s `baseline_units` for lines covering the window, so it matches the uplift below.
  - Each option adds its `window_uplift`: its units less baseline in the weeks of the window, from `line_paths`. That nets off the pull-forward dip where it falls inside the window.
  - A BUNDLE adds its partner's `partner_window_uplift` to the partner's target.
  - Cannibalisation of a clearance SKU by other plan lines is not counted, which keeps the constraint linear.
  - The uplifts are computed only for options that touch a clearance SKU, so the demo path is unchanged.

  A region where the SKU has no available stock gets no target. We rejected the oracle's per-line sell-through (ADR 0017), because it would force a promotion even when the baseline alone reaches the target.
- **A SKU named for clearance counts as overstocked** in every region of the scope, as ADR 0035 already planned. It may sell below unit cost and earns clearance value. Option generation, the solver and `validate_plan` all apply this.
- **"Hard, then soft if infeasible" is a two-phase solve.** This is how the issue's "hard by default and, if infeasible, re-solved as soft with a reported shortfall" is implemented, and it runs only when the request has clearance targets:
  1. The first phase finds the plan closest to every target under every other constraint. It minimises the stock left short, each unit weighted by its unit cost: the rupees of stock that stay short of target.
  2. Each target is then lowered to what that plan reaches, and the second phase maximises the objective as usual.

  When every target is reachable, the first phase finds no shortfall and the second phase is exactly the hard model. When one is not, the result is what a very large penalty would give. Its status is the second phase's own (`OPTIMAL`, or `FEASIBLE` if either phase ran out of time), and `clearance_shortfalls` lists each missed target with the expected sell-through and the units short. `validate_plan` reports each one as a `CLEARANCE_TARGET` violation, so a miss is never silent.
  - The empty plan is always feasible in the first phase, so there is always an answer. That settles ADR 0036's open "no plan in time" case: if the second phase finds nothing in time, the first phase's plan is returned. It keeps every constraint, the lowered targets included.
  - The two phases share the optimiser's time limit: the first gets half, the second what is left, and at least half.
  - Lowering each target separately can cost some objective against a pure penalty when two targets could trade shortfall between them. We accepted that for a sound binding analysis on ordinary linear constraints.
  - We rejected solving hard first and re-solving only after CP-SAT proves infeasibility. Proving infeasibility can be slow on knapsack-like models, and a timeout would need a new "unknown" status.
- **Options that sell towards a target are eligible even when they lose money alone.** A target the brief set is the justification (F-01 AC1). Such a line's "why chosen" gains `clearance_target`, with the units it adds over the window. Only when no line of the SKU sells towards the target does the plan fall short.
- **Every plan-level constraint is one linear row**, `Σ x·a ≤ b` in whole paise or thousandths of a unit:
  - the marketing budget;
  - each regional cap;
  - the margin;
  - each promoted-SKU cap;
  - each clearance target, as −units sold ≤ −need;
  - the KVI tolerance, as the count of breaking options ≤ 0.

  Costs round up, budgets and caps down, and units sold towards a target round down. So a plan the solver accepts passes `validate_plan`.

  The binding analysis (ADR 0038) works on these rows generically: `_can_bind`'s static bound, the swap check's arrays, `_evaluate`, and the "breaking" re-solve (`Σ x·a ≥ b + 1`). Each new constraint has:

  | Constraint | `ConstraintKind` | Source | Not-selected reason |
  |---|---|---|---|
  | Regional cap | `regional_budget` | brief | `over_regional_budget` |
  | Clearance target | `clearance_target` (with `sku_id` and region) | brief | `misses_clearance_target` |
  | KVI tolerance | `kvi_price_tolerance` | brief, or company_policy when policy turns it on | `breaks_kvi_tolerance` |

  A brief-tightened promoted-SKU cap is reported with source `brief`. A lowered clearance target is reported at the sell-through actually applied.
- **The KVI tolerance is a plan-level constraint, not a per-line filter.** Options that break it stay in the model, forced out unless the tolerance is dropped, so the binding analysis can say what the rule costs. The rule is ADR 0031's one-sided check. Options that break the tolerance do not count as eligible, and are not an option's best rival in "why chosen". When the tolerance is off, no option breaks it and nothing changes.
- **A price-match option for each undercut KVI.** A KVI undercut beyond the company-policy threshold in a scope region gets a PCT_OFF option at the smallest whole-percent depth whose price is at or below the competitor's. It is enumerated for every timing and target segment, and pruned like any other option.
  - It is added only when that depth is not already on the grid.
  - `PromoOptions.price_matches` and the `generate_candidates` summary list each match, so E8's planner can say "matching on N SKUs" (F-08 AC2).
  - Matches are always generated; #47 may add a switch.
  - We rejected a FIXED_PRICE match, which often lands several percent below the competitor. We also rejected an exact paisa match, which needs a non-integer depth on `PlanLine`.

## Result on the seed-42 demo brief

- The demo brief sets no optional constraint. It gains the price matches of the three KVIs undercut in the North: SKU0002 at 14%, SKU0036 at 13% and SKU0037 at 14%.
  - Generation enumerates 29,025 options (45 more) and keeps 10,435.
  - 1,947 options are eligible, with the same 3,796 pairwise terms.
  - The plan is unchanged: `OPTIMAL`, 35 lines, ₹172,384 for ₹199,909 of promo cost. No price match pays its way.
  - Timed back to back on the same candidate set, `solve` takes 7.1–7.2 s against main's 7.3–7.6 s.
- With a 50% clearance target on SKU0029 (overstocked in both regions), a ₹90,000 North cap and a 2% KVI tolerance:
  - The plan is `OPTIMAL`, with 37 lines worth ₹170,982 for ₹199,953 of promo cost. It meets the target in both regions, so there is no shortfall.
  - 2,186 options are eligible, with 5,719 pairwise terms. `solve` takes about 8 s, within the 10 s budget.
  - With the default 8 s binding limit, the budget, both Beverages caps and the North cap are proven binding (`lower_bound`). The clearance targets, the KVI tolerance, the margin floor and the Snacks caps stay `unproven`.

## Consequences

- Sessions and `generate_candidates` read the latest competitor gaps at the as-of week for the scope's regions (`read_competitor_gaps`). `FittedOptionFacts.sku` now also returns each SKU's KVI flag and competitor price.
- Migration 0007 adds nullable `clearance_shortfalls` and `policy_findings` columns to `plan_revisions`, on top of #38's 0005 and #39's 0006. The OpenAPI types and the web app's zod schemas follow; E10 displays them.
- The hypothesis properties now draw clearance targets, regional caps, KVI tolerances and brief caps.
  - Every plan passes `validate_plan` except for its reported clearance shortfalls.
  - A brute force confirms that the shortfall is the least any plan can leave, and that the objective is optimal when every target is reachable.
  - Tightening the budget or the margin never lowers the shortfall. Where both plans reach every target, it never raises the objective.
  - For regional caps, the KVI tolerance and each clearance target, a constraint is reported binding exactly when dropping it gains, and by exactly that gain, whenever the plan reaches every target.
- **Notes for #37 (relaxation).** Clearance targets alone never make a request `INFEASIBLE`. The relaxation for a clearance target can be read straight off `clearance_shortfalls`: lower it to the expected sell-through reported. A hard-only switch, where a missed target gives `INFEASIBLE` plus a relaxation, would be a first-phase shortfall above zero with the empty plan. Regional caps and the promoted-SKU cap can never make the empty plan infeasible either.
- **Notes for #46 (Context agent).** It must extract the four fields into `BriefReading`, which means re-recording cassettes. It turns a `PolicyFinding` into a flagged assumption, and asks for a clearance figure the brief leaves out.
