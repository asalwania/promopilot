# An infeasible request is one no plan reaches every clearance target of; its relaxation minimises the relative change to the brief's own constraints

E6 (#37) makes the optimiser declare an impossible request infeasible, never a silently broken plan, and propose the smallest relaxation of the brief's constraints that would make it feasible (SPEC §9.4, AG-06). Company policy is never relaxed, and when only policy binds the optimiser says so (ADR 0007).

SPEC and ADR 0007 name the relaxable constraints (budget, minimum margin down to the floor, clearance target, scope). They leave open:

- what makes a request infeasible once #36 made clearance targets soft;
- how a timeout is told apart from infeasibility;
- whether #36's regional caps, KVI tolerance and tighter promoted-SKU cap may be relaxed;
- what "scope" means as a slack;
- how slack is normalised and weighted;
- what "policy binds" means;
- where the relaxation lives.

We chose these with the owner.

## What infeasible means

- **A request is infeasible when no plan reaches every clearance target within its other constraints.** Nothing else can make it infeasible. Every other plan-level constraint is an upper bound that the empty plan keeps:
  - the budget and the regional caps;
  - the margin row Σ x·(m·revenue − gross profit) ≤ 0;
  - the promoted-SKU caps;
  - the KVI tolerance.

  #36's first phase already finds the plan closest to every target (ADR 0040). A proven shortfall above zero is therefore a proof of infeasibility.
- **An infeasible result keeps the closest plan.** Its status is `INFEASIBLE`. It still has the plan, why each line was chosen, the not-selected list and the clearance shortfalls (ADR 0040), and it adds:
  - the binding constraints of an infeasible request;
  - the relaxation.

  This follows SPEC §9.4 ("soft … reported as a violation") and F-06 AC2 ("the plan states clearly that it is infeasible and by how much"). A plan labelled `INFEASIBLE`, with its shortfalls, is not a silently broken plan. We rejected returning an empty plan, which drops what #36 found. We also rejected keeping `OPTIMAL` with a shortfall, which never says infeasible.
- **A timeout is never reported infeasible.** If phase 1 runs out of time with a shortfall, it has not proven that no plan does better. The status is then `FEASIBLE`, the shortfalls are reported, and the relaxation is still attached with `proven: false`. Without clearance targets, a solve that finds nothing in time still returns the empty plan as `FEASIBLE`: the empty plan really is feasible there (ADR 0036).
- **The binding constraints of an infeasible request** are:
  - each (SKU, region) clearance target the plan misses;
  - each constraint the relaxation changes;
  - for a promoted-SKU cap, each (category, region) the relaxed plan fills beyond it.

  Each is reported at the brief's value, with a new evidence `infeasible` and no objective gain. ADR 0038's binding analysis does not run: its question, whether dropping a constraint improves the objective, has no meaning without a feasible optimum.

## What may be relaxed

- **Only constraints the brief set, and only as far as policy allows:**

  | Constraint | Relaxed | Never past |
  |---|---|---|
  | Marketing budget | up | — |
  | Regional budget cap | up | — |
  | Minimum margin (the brief's, above the floor) | down, in 0.5-point steps | the company-policy margin floor |
  | Promoted-SKU cap the brief tightened | up | company policy's cap |
  | KVI price tolerance the brief turned on | off | company policy's tolerance, where policy turns it on |
  | Clearance target | down, or dropped | — |

  #36's regional caps, tighter SKU cap and KVI tolerance are brief constraints (source `brief`, ADR 0040), so they are relaxable in the same way. A regional cap is part of "budget" in SPEC §9.4. The margin floor, a policy SKU cap, a KVI tolerance policy turns on, the maximum discount, the below-cost rule, stock and the window are never relaxed.
- **A clearance target is relaxed per SKU, as the request holds it.** `ClearanceTarget` has one sell-through per SKU, applying in every scope region (ADR 0040). So the relaxation lowers the SKU's single target until every region reaches it, and applying it just rewrites `clearance_targets`. We rejected per-region targets, which would change the request, the contract and the migration.
- **Scope is not a slack.** Narrowing scope only removes targets, and dropping a target is always a bigger change than lowering it. Widening scope, such as a longer promo window, means generating options again, which takes 7–9 s on the demo world. "Extend the promo window" is a follow-up (below).

## How small is smallest

- **Each change is weighed as a share of the brief's own value, in basis points, all weights 1**:
  - ₹2 lakh → ₹2.2 lakh is 1,000;
  - a 25% → 22.5% minimum margin is 1,000;
  - a 50% → 45% target is 1,000;
  - a cap of 4 → 5 is 2,500;
  - the KVI tolerance off, or a target dropped, is 10,000.

  The relaxation minimises their sum. There is no new weight config. We rejected per-kind weights in config, and rupee-denominated slack (budget rupees, units short × unit cost, margin points × revenue), which is honest but mixes units and is harder to explain.
- **It is one CP-SAT model, exact in whole numbers:**
  - The budget and each regional cap become BASIS_POINTS·Σ x·cost ≤ BASIS_POINTS·budget + budget·r, with r in basis points.
  - A clearance target row is scaled the same way. Its slack is shared by every region of the SKU. A second 0/1 variable drops the target at 10,000.
  - The minimum margin is bilinear in x and the margin. So it is one row per 0.5-point level, from the brief's minimum down to the floor, each enforced by a one-of-many choice costing its change.
  - A brief cap is `≤ cap + r`, with r up to policy's cap. The KVI row is enforced unless a 0/1 "off" is paid for.
- **The values reported are what the plan found actually needs**, not the grid it was found on:
  - a budget or cap at what the plan spends, to the paisa;
  - the minimum margin at the plan's blended margin, to a basis point;
  - the SKU cap at the most the plan promotes;
  - a target at the least sell-through any region reaches, to a basis point, or dropped below one basis point.

  Each is checked with the solver's own rounding, so the relaxed request always admits that plan. `optimizer.relaxed_request(request, relaxation)` applies a relaxation. Re-solving the result is feasible, which a hypothesis property checks.

## Policy binds

- **Two re-solves share `OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS`** (default 10 s):
  1. The first frees every brief constraint but the targets as far as policy allows, at no cost, and minimises the targets' change alone. If a target must still come down, **company policy binds**: no change to the budget, caps, margin or tolerance alone would reach it. `policy_binds` is then true, and each target the policy re-solve lowers gets `policy_allows`, the most sell-through policy allows.
  2. The second finds the least total change.

  Each gets half the limit; the second gets whatever the first leaves, and at least half. `proven` is true only when phase 1 and both re-solves reached optimality. If the second finds nothing in time, the closest plan gives the relaxation: each target lowered to what that plan reaches, as ADR 0040 foresaw.
- We rejected naming which policy rule binds: the margin floor, a policy cap, or a per-line rule such as stock or the maximum discount. That needs a re-solve per rule. It still cannot name a per-line rule, whose options were pruned at generation.

## Where it lives

- **`solve` computes the relaxation** whenever phase 1 leaves a shortfall (SPEC §9.4: "for infeasible cases the minimal relaxation found by re-solving with slack variables"). It appears in three places:
  - on `OptimisationResult.relaxation`;
  - on `run_optimizer`'s output;
  - on the plan revision, as `PlanRevision.relaxation` (migration 0008, JSONB).
- **`relax_constraints`**, the planner's tool, takes the same `candidate_set_id` as `run_optimizer`. It returns:
  - the status;
  - the relaxation (`null` when the request is feasible);
  - the binding constraints of an infeasible request;
  - the shortfalls and the policy findings.

  It skips the binding analysis, which is `run_optimizer`'s job.
- **Domain types (ADR 0009):** `Relaxation` (`changes`, `policy_binds`, `proven`) and `RelaxedConstraint` in `promopilot.domain`. A `RelaxedConstraint` holds:
  - `kind` and `source` (always `brief`);
  - `region` or `sku_id`;
  - `current`, `relaxed` (None drops it) and `change` (the share);
  - `policy_allows`.
- **The session's status stays `awaiting_approval`**, so the manager can amend. Blocking approval of an infeasible plan is left to E8/E10. The web app's schemas follow the regenerated types. An infeasible revision says "Infeasible: no plan reaches every clearance target within the brief's constraints" instead of the empty-plan message. E10 shows the relaxation.
- **Sessions cannot carry clearance targets until #46** (ADR 0040), so a brief cannot yet produce an infeasible session. The API test plans a session through a planner that adds a target the brief cannot carry.

## Result on the seed-42 demo world

The demo brief sets no clearance target, so it never reaches the relaxation. Its plan and timing are unchanged: `OPTIMAL`, 35 lines, ₹172,384.

On the same world, with SKU0029 (overstocked in both regions) named for clearance:

- **A 90% target, ₹2 lakh budget.** The result is `INFEASIBLE`: the closest plan reaches 70.3% in the North and 82.4% in the West. Policy binds, and the relaxation lowers the target to 70.27% (a 21.9% change; policy allows 70.27%). Re-solved with it, the request is `OPTIMAL`, with 31 lines worth ₹162,628.
- **A 60% target, ₹20,000 budget.** The result is `INFEASIBLE`, and policy does not bind: more budget would reach the target. But the smallest change lowers it to 39.77% (a 33.7% change), because that costs less than the budget rise that reaching 60% would need.
- **A 50% target, ₹20,000 budget, 30% minimum margin.** The result is `INFEASIBLE`. The relaxation raises the budget by 1.7% to ₹20,344.46 and lowers the target to 39.77% (20.5%); neither change alone suffices.
- **A 45% target, ₹20,000 budget.** The result is `INFEASIBLE`, and policy does not bind. The relaxation lowers the target to 39.77% (an 11.6% change).
- **Timings**, measured under load from parallel agents:
  - The relaxation's two re-solves take 0.35–1.7 s.
  - A whole infeasible `solve` takes 5.5–7 s: both phases plus the relaxation, with no binding analysis.
  - The demo brief's own `solve`, without the binding analysis, took 9.7 s against the 10 s budget, unchanged by this ADR.
  - Candidate generation took 13–17 s under the same load.

## Consequences

- **Feasible requests pay nothing.** The relaxation runs only when phase 1 leaves a shortfall, and the demo brief has no clearance target. An infeasible solve skips ADR 0038's binding analysis, which takes up to 8 s. It spends the relaxation's two re-solves instead, 0.35–1.7 s on the demo world, so an infeasible session is faster than a feasible one and SPEC's 60 s end to end is unaffected.
- #36's hypothesis properties now expect `INFEASIBLE` exactly when a clearance target is missed. New properties, over #36's instances and a squeezed strategy where brief constraints often cause the infeasibility, check that:
  - infeasible instances are `INFEASIBLE` exactly when a brute force finds no plan reaching every target;
  - applying the relaxation makes the instance `OPTIMAL` with no shortfall;
  - a relaxation never touches company policy;
  - `policy_binds` matches a brute force with every brief constraint freed;
  - no change of a proven relaxation can be left out.
- **Follow-ups:**
  - extending the promo window as a scope relaxation;
  - naming which policy rule binds;
  - #46 reads clearance targets and caps from the brief, and turns a relaxation into an amendment the manager can accept;
  - E10 displays the relaxation.
