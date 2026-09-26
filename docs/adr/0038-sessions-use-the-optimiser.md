# Planning sessions use the optimiser, with proven binding constraints and structured reasons for each plan line and each rejected option

E6 (#35) replaces the E3 naive planner in the planning session with option generation and the CP-SAT optimiser (ADR 0035, ADR 0036). The issue says:

- the plan revision stores the solver status, the binding constraints named in domain terms, and the top 5 options left out, each with a reason;
- each plan line carries a structured "why chosen" reason.

SPEC §9.4 says binding constraints are "detected from slack/tightness at the solution". The issue's test says something different: relaxing a reported binding constraint changes the objective, and relaxing a non-binding one does not. Neither says which constraints count, what a reason looks like, or how a session reaches the models. We chose these with the owner:

- **A constraint binds when dropping it gives a strictly better objective.** In a 0/1 programme, slack cannot tell this:
  - a budget can bind with ₹10 left over when the next option costs ₹50;
  - a promoted-SKU cap can bind while it is not full.

  After an `OPTIMAL` solve, `solve` settles each candidate constraint in up to four steps, cheapest first. Each step is sound, so a wrong result is never reported. Every step reuses the pairwise terms already priced, and none prices them again.
  1. **A static check rules out constraints no plan could fill.** At most one line is anchored on each (SKU, region), so:
     - no plan costs more than the sum, over anchors, of their costliest option;
     - no plan falls further short of the margin than the sum of their largest positive shortfalls;
     - a promoted-SKU cap counts each SKU of its category and region at most once.

     If the budget covers that cost, the margin line that shortfall, or the cap every such SKU, the constraint cannot bind. It is not reported, and no solve is needed. A cap that is not full can still bind, so fill level alone is never used.
  2. **A swap proves the constraint binds.** The current plan is optimal with every constraint. So any strictly better plan that keeps all constraints but one proves that one binds. One option is swapped into the plan, taking out the lines it clashes with and at most one more line. All swaps are scored at once on arrays, and the best is re-checked from scratch before it counts. It proves binding with the gain as a `lower_bound`.
  3. **A re-solve settles what is left.** For each constraint still unsettled, the model is re-solved without it. The re-solve starts from the current plan and asks for a plan at least a paisa better that breaks the dropped constraint, since any better plan must break it. The search stops at the first plan found:
     - such a plan proves the constraint binds: `lower_bound`, or `exact` if the solver also proved it optimal;
     - infeasibility proves it does not bind, and it is not reported.
  4. **Leftover time makes gains exact.** Any time still left goes to re-solving the `lower_bound` constraints to optimality, starting from the better plan already found. Those that reach optimality become `exact`.

  Anything still unsettled when the time runs out is reported `unproven`, with no gain. It is never skipped silently.

  We rejected slack/tightness, which breaks the issue's test in both directions. We also rejected re-solving only the tight constraints, which misses caps that are not full.
- **The binding analysis has its own time limit.** `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS` defaults to 8. Steps 1–2 take milliseconds. In step 3, each re-solve gets an even share of what is left, and never more than `OPTIMIZER_TIME_LIMIT_SECONDS`. A re-solve can overrun its share by about one model build (0.1–0.3 s).
  - **The optimiser's 10 s budget (SPEC §15 E6) does not include the binding analysis.** That budget covers `solve` itself: pricing the pairwise terms, the solve, "why chosen" and the not-selected list. The binding analysis is a separate post-step that runs within its own limit. Candidate generation is outside the budget too (#113).
  - At 8 s the full demo plan takes about 9 s of generation, 6 s of solving and 8 s of binding analysis, well within SPEC's 60 s.
  - If the plan itself is not proven optimal (`FEASIBLE`), every constraint that could bind is reported `unproven`, with no re-solve. A better plan without a constraint would prove nothing when the plan could have been improved anyway.
  - Time-limited re-solves depend on the machine, so their evidence may differ between machines. The plan does not change.
- **Candidates are the plan-level constraints only.** They are:
  - the marketing budget (source `brief`);
  - the margin. It is named `minimum_margin` (source `brief`) when the brief's minimum is above the company-policy floor, and `margin_floor` (source `company_policy`) otherwise, so the manager is told when policy binds (ADR 0007). Dropping it removes the margin constraint entirely.
  - each (category, region) promoted-SKU cap (source `company_policy`).

  Per-line rules are not binding constraints: stock, window, maximum discount, below cost, and one line per SKU per region. They show up as reasons in the not-selected list.
- **Why chosen** is a `WhyChosen` on each plan line:
  - `reasons`: one `{code, amount}` for each positive part of the line's value, from `incremental_profit`, `clearance_value` and `halo`. Only options worth at least a paisa are eligible (ADR 0036), so every line has at least one.
  - `value`: what the line is worth alone.
  - `best_for_sku_region`: whether it is the best eligible option for its SKU and region.

  E8's Explainer turns these into text. We rejected a single primary code, and naming the constraint that pushed a line off its best option, which needs more re-solves.
- **Not selected** means up to 5 (SKU, region)s with no plan line, a BUNDLE partner counting as having one.
  - Each is shown with its best-value option from the candidate set, ranked by that value.
  - Each lists every rule the option breaks on its own or when added to the plan: `low_uplift` (worth less than a paisa), `out_of_stock`, `breaks_policy` (window, maximum discount or below cost), `over_budget`, `breaks_margin`, `max_promoted_skus`, and `cannibalises` (pairwise terms with named plan lines outweigh its value, and `cannibalises` lists their SKUs).
  - `time_limit` appears only when the plan is not proven optimal and nothing else applies.

  Generation already prunes out-of-stock options (ADR 0035), so `out_of_stock` shows only for hand-built candidate sets. In a real session, stock pruning stays a count. We rejected keeping the stock-pruned options, which would need effects for thousands more lines, and listing the top 5 individual options, which mostly repeats other depths of SKUs already in the plan.
- **The session calls the optimiser directly.** `OptimisingPlanner`:
  1. resolves the latest demand model and the live relations model on every plan;
  2. pools the as-of week's inventory;
  3. generates the full option grid;
  4. solves;
  5. builds plan revision 1.

  E8's planner agent will drive the same work through `generate_candidates` and `run_optimizer`. `run_optimizer` now returns the binding constraints, each line's `why_chosen` and the not-selected list too. With no trained model, a session fails with "no demand model … is trained yet: run make train".
- **Reading the brief is split from planning.** `read_planning_request` is the only step that calls an LLM. So `make record-cassettes` and the committed-cassette test need no trained model, and plans are never recorded.
- **`SolveStatus` and the new value types live in `promopilot.domain`** (ADR 0009): `BindingConstraint`, `BindingEvidence`, `WhyChosen` and `NotSelectedOption`. The optimiser re-exports `SolveStatus`.
- **Persistence.** Migration 0004 adds nullable columns:
  - on `plan_revisions`: `solver_status`, `objective`, `binding_constraints` (JSONB) and `not_selected` (JSONB);
  - on `plan_lines`: `why_chosen` (JSONB).

  Revisions from before the optimiser read back with a null status and no reasons.
- **The frontend only follows the contract.** The zod schemas and fixtures follow the regenerated types. The empty-plan message now says that no promo option pays for itself within the brief's constraints. The Playwright journey waits up to 2 minutes for the plan. E10 shows the new fields.

## Consequences

- On the seed-42 demo brief (after #112), the plan is `OPTIMAL` with 35 lines, worth ₹172,384.
  - `solve` takes about 6 s without the binding analysis and about 14 s with the default 8 s. To keep the reports inside the 10 s budget, finding which option pairs could run together is now decided on arrays rather than pair by pair, and only non-zero pairwise terms are kept (a pair of eligible options that is absent has a zero term).
  - Swaps prove, in about 10 ms, that the marketing budget (gain at least ₹2,241) and both Beverages caps (North at least ₹193, West at least ₹450) bind, as `lower_bound`.
  - Proving that the margin floor and both Snacks caps do not bind takes CP-SAT about 4 s each, so with the default limit they stay `unproven`.
  - With a 30 s limit all six settle. The budget and the Beverages caps become `exact` (₹8,030, ₹1,385 and ₹1,732), and the other three are proven not to bind.
- #112's demo speed test (marker `model`) times `solve` with the binding analysis off, against the 10 s budget. It also checks that every line has a reason and that at most five options are left out. A second test checks two things with the default limit: the analysis overruns by no more than its limit plus model builds, and the marketing budget is proven binding.
- #36 adds clearance targets, regional caps and the KVI tolerance. Each is a new plan-level constraint and must join:
  - `_limits` and `_can_bind`;
  - the swap check;
  - the "breaking" re-solve;
  - a `ConstraintKind`, a source, and a not-selected reason.

  A clearance target can make the empty plan infeasible, so the "no plan in time" case needs revisiting (ADR 0036).
