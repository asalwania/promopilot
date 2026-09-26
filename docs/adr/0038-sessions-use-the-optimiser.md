# Planning sessions use the optimiser, with proven binding constraints and structured reasons for each plan line and each rejected option

E6 (#35) replaces the E3 naive planner in the planning session with option generation and the CP-SAT optimiser (ADR 0035, ADR 0036). The issue says:

- the plan revision stores the solver status, the binding constraints named in domain terms, and the top 5 options left out, each with a reason;
- each plan line carries a structured "why chosen" reason.

SPEC §9.4 says binding constraints are "detected from slack/tightness at the solution". The issue's test says something different: relaxing a reported binding constraint changes the objective, and relaxing a non-binding one does not. Neither says which constraints count, what a reason looks like, or how a session reaches the models. We chose these with the owner:

- **A constraint binds when dropping it gives a strictly better objective.** In a 0/1 programme, slack cannot tell this:
  - a budget can bind with ₹10 left over when the next option costs ₹50;
  - a promoted-SKU cap can bind while it is not full.

  So after an `OPTIMAL` solve, `solve` re-solves once for each constraint, without that constraint. Each re-solve:
  - starts from the plan it found;
  - asks for a plan at least a paisa better;
  - reuses the pairwise terms already priced, so it never prices them again.

  The outcome of each re-solve:
  - **infeasible**: no better plan exists, so the constraint does not bind and is not reported;
  - **optimal**: the constraint binds with an `exact` gain;
  - **timed out after finding a better plan**: it binds, and the gain is a `lower_bound`;
  - **timed out without finding one, or no time left**: it is reported as `unproven`, with no gain. It is never skipped silently.

  We rejected slack/tightness, which breaks the issue's test in both directions. We also rejected re-solving only the tight constraints, which misses caps that are not full.
- **The re-solves share their own time limit.** `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS` defaults to 3. Each re-solve gets an even share of what is left, and never more than `OPTIMIZER_TIME_LIMIT_SECONDS`.
  - **The optimiser's 10 s budget (SPEC §15 E6) does not include the binding analysis.** That budget covers `solve` itself: pricing the pairwise terms, the solve, "why chosen" and the not-selected list. The binding analysis is a separate post-step that runs within its own limit, so `solve` takes at most that much longer. Candidate generation is outside the budget too (#113).
  - If the plan itself is not proven optimal (`FEASIBLE`), every candidate constraint is reported `unproven` with no re-solve. A better plan without a constraint would prove nothing when the plan could have been improved anyway.
  - Time-limited re-solves depend on the machine, so their evidence may differ between machines. The plan does not change.
- **Candidates are the plan-level constraints only.** They are:
  - the marketing budget (source `brief`);
  - the margin. It is named `minimum_margin` (source `brief`) when the brief's minimum is above the company-policy floor, and `margin_floor` (source `company_policy`) otherwise, so the manager is told when policy binds (ADR 0007). Dropping it removes the margin constraint entirely.
  - each (category, region) promoted-SKU cap (source `company_policy`), and only where more eligible options could fill it than it allows.

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

- On the seed-42 demo brief, the plan is `OPTIMAL` with 32 lines. `solve` takes about 22 s:
  - 14 s pricing pairwise terms (#112 speeds that up);
  - about 4 s for the solve;
  - the 3 s binding limit.

  Each of the six binding re-solves needs 3–6 s there. So with the 3 s default, all six are reported `unproven`. With 60 s they settle: the budget and both Beverages caps bind exactly, and the margin and both Snacks caps do not. The not-selected list's top five are each `over_budget` and `max_promoted_skus`.
- The performance test (marker `model`) times `solve` on the demo scope with the binding analysis switched off (`binding_time_limit_seconds=0`). Its 10 s assertion is `xfail` until #112 makes pairwise pricing fast; after #112 the core solve is expected at about 6–7 s. A second test checks that every plan line says why it was chosen and that the not-selected list has at most five entries.
- #36 adds clearance targets, regional caps and the KVI tolerance. Each is a new plan-level constraint and must join `_limits`, with a `ConstraintKind`, a source and a not-selected reason. A clearance target can make the empty plan infeasible, so the "no plan in time" case needs revisiting (ADR 0036).
