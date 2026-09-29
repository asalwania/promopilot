# A plan that misses a clearance target is INFEASIBLE, settled by a feasibility check when the closest-plan search runs out of work; a solve that finds no plan in time returns the greedy plan

#156 comes from #58's target review of the first full eval run. Three scenarios failed because a plan the solver returned after running out of work was passed on unchecked:

- `clear-curd-diwali-2025` came back `FEASIBLE` with 19 lines. SKU0057 in North reached 28.3% sell-through against a 50% target, 867 units short.
- `diwali-2025-home-personal-care` and `tight-offseason-beverages` came back `FEASIBLE` with 0 lines.

The decision gate reproduced all three offline and measured the solver on the eval world's fitted models:

- **clear-curd.** The closest-plan search (phase 1, ADR 0040) ends at the same 867-unit shortfall with 5, 15 and 50 deterministic seconds, and never proves it. So ADR 0044 made the result `FEASIBLE`, with an unproven relaxation.
  - With every target a hard constraint and no objective, CP-SAT proves the request infeasible at presolve, in 0.6 s.
  - SKU0057 North alone can be reached: forcing a BOGO 50% or a FIXED_PRICE 25% line gives a plan at once. Those lines break the margin row on their own, though, and the other lines can make up for that for one target but not for all six.
  - Proving the least shortfall is hard for CP-SAT; proving that some shortfall must remain is trivial. An LP bound does not prove it, and neither does a per-target static bound.
- **The empty plans.** There are no clearance targets, so there is only one phase. It found no solution within its 10 deterministic seconds (UNKNOWN), and `solve` returned the empty plan as `FEASIBLE`.
  - The models are large: 3,262 and 5,722 eligible options, and 21,416 and 41,376 pairwise y variables.
  - With 30 deterministic seconds they give 7 lines (₹63.9k, OPTIMAL) and 68 lines (₹152.6k, FEASIBLE).
  - A greedy plan takes under a second: 3 lines (₹43.9k) and 21 lines (₹308.9k). Using it as a CP-SAT hint gains 0.02–0.6% for another 60–70 s of wall time.
- **The Explainer's fallback** said "No promo option pays for itself" for an empty `FEASIBLE` plan. That is false after a timeout.

We chose these with the owner (D1–D8 on #156; every recommended option).

## Decisions

- **D1. When phase 1 runs out of work short of a target, a feasibility check settles it.**
  - The check has every constraint hard, each clearance target at the brief's value, and no objective. It stops at the first plan found (`stop_after_first_solution`), hinted with the closest plan.
  - **INFEASIBLE:** the request is proven infeasible. The status is `INFEASIBLE`, with the relaxation, and binding evidence `infeasible`, as when phase 1 proves its shortfall.
  - **A plan found:** every target is reachable. The check's plan replaces the closest plan, the targets stay the brief's, and the main solve starts from it. If the main solve finds nothing better in time, the check's plan is returned.
  - We rejected marking every unproven shortfall `INFEASIBLE` with no check, which would call reachable targets unreachable. We also rejected longer phase-1 budgets: clear-curd's shortfall stays unproven at 50 deterministic seconds.
- **D2. A missed target is never `FEASIBLE`.** When the check also runs out of work, the status is still `INFEASIBLE`, with binding evidence `infeasible`. The relaxation then has `proven: false`.
  - Approval is refused for an `INFEASIBLE` revision (ADR 0046 D10), so the manager must accept the relaxation first. Accepting it lowers each target to what the plan reaches, so the amended request is feasible.
  - We rejected keeping `FEASIBLE` there, as ADR 0044 had it. A plan that misses a target the manager set could then be approved.
- **D3. The check's budget comes from the relaxation's.** It takes up to half of `OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT` and of `OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS`. The relaxation gets what the check left, at least half, and splits it between its two re-solves as before.
  - The main solve's budget and wall-clock net are unchanged: the check's time is not taken from them.
  - There is no new setting, and the cassette manifest's recorded settings are unchanged.
  - We rejected a new `OPTIMIZER_FEASIBILITY_DETERMINISTIC_LIMIT`, which needs `.env.example`, the README and the manifest. We also rejected taking the check's share from the main solve's 10.
- **D4. Without clearance targets, a main solve that finds nothing but the empty plan in time returns the greedy plan.**
  - The greedy plan takes options best value first, ties to the earlier option. Each option joins when:
    - it keeps every constraint;
    - it keeps one line per SKU and region;
    - it runs with no plan line of a strong substitute (ADR 0075), which the check (D1) also keeps, since it uses the same model;
    - it gains at least a paisa net of its pairwise terms with the lines already in.
  - It is pure numpy, with no CP-SAT work and no clock, so the same input gives the same plan and there is no new exposure to the wall-clock net. It takes under a second on the largest eval scope.
  - The status is `FEASIBLE`, and every constraint that could bind is reported unproven.
  - With clearance targets, the closest plan (or the check's plan) is returned as before.
  - Both conditions trigger it: the main solve ending UNKNOWN, or ending FEASIBLE with the empty plan. The empty plan and the greedy plan both keep every constraint, and the greedy plan is never worse.
  - If the greedy plan is also empty, no option keeps every constraint alone, and the empty plan comes back as `FEASIBLE`.
  - We rejected a greedy-hinted re-solve, which gains 0.02–0.6% for 60–70 s more wall time and risks the wall-clock net. We rejected always hinting the main solve with the greedy plan, which changes every solve's search path and so every cassette. We rejected retrying on a 3× budget (slow, and still not guaranteed) and a new "no plan in time" status (API, types and web changes).
- **D5. The plan-quality metric's best plan uses the same `solve`** (ADR 0063), with no eval code change.
  - clear-curd's best plan becomes `INFEASIBLE`, so it is left out as `best_infeasible`.
  - diwali-2025-home-personal-care's best plan becomes the greedy plan.
  - tight-offseason-beverages's best plan is unchanged (OPTIMAL).
- **D6. `clear-curd-diwali-2025` now expects `declares_infeasible: true`** and no longer expects `meets_clearance`. Its brief and labels are unchanged, and so is its group (`overstock_clearance`).
  - So the suite's rules (ADR 0065) now allow an `overstock_clearance` scenario to expect `declares_infeasible: true`. Such a scenario expects no `meets_clearance`, since its targets are out of reach. Every other rule is unchanged.
  - We rejected loosening the brief (for example one SKU or a 40% target), which changes the Context request and so the whole recording.
- **D7. The wall-clock net finding is recorded here and followed up in #166.**
  - On these large scopes, CP-SAT's own wall time for 10 deterministic seconds was 52–105 s on a shared development machine. ADR 0055 assumed about 13 s. That is at or over the main solve's 60 s net, so on big scopes the net, not the work budget, can decide where the search stops.
  - #156 does not hide or cause this. The candidate fixes change the solver model (one-sided y linking by the sign of the pairwise charge, which halves the pairwise constraints) and would collide with #158, or adjust the nets.
- **D8. The Explainer's template summary says what was found, not what was proven.**
  - An empty `FEASIBLE` plan says "No plan was found within the optimiser's work budget."
  - An `INFEASIBLE` plan whose relaxation is not proven says "no plan found within the optimiser's work budget reaches every clearance target, so this is the closest plan found."
  - Only the template changes. The plan data the Explainer's LLM request carries is unchanged.

## What this amends

- **ADR 0044:** "A timeout is never reported infeasible" is replaced by D1 and D2. A plan that misses a target is `INFEASIBLE`: proven by phase 1 or by the check, and otherwise with `proven: false`. "Without clearance targets, a solve that finds nothing in time still returns the empty plan as `FEASIBLE`" is replaced by D4.
- **ADR 0036:** a solve that finds no plan in time returns the greedy plan, not the empty plan.
- **ADR 0055:** the relaxation budget now also pays for the check (D3). The wall-clock net can be reached on large scopes (D7).
- **ADR 0065:** only the `infeasible_constraints` group could expect a declared infeasibility, and every `overstock_clearance` scenario expected `meets_clearance` for each target. A clearance scenario whose targets no plan reaches now expects `declares_infeasible: true` instead (D6).

## Consequences

- **Tests** (all on deterministic budgets, never on wall-clock limits):
  - phase 1 starved of work and the check given work: the request is proven `INFEASIBLE`, with a proven relaxation and `infeasible` binding evidence;
  - the same with reachable targets: no shortfall and no relaxation;
  - the check starved too: `INFEASIBLE`, with `proven: false`;
  - a starved solve without targets returns the greedy plan, by hand (a budget, a SKU clash and a pairwise term each keep an option out), and it keeps the strong-substitute rule;
  - a hypothesis property over #36's instances with every phase starved: every plan keeps every hard constraint, it is `INFEASIBLE` exactly when a shortfall is reported, and without targets it is empty only when the best plan is;
  - the Explainer's two new template sentences.
- **LLM requests.** The tool descriptions, `SolveStatus`, the API and the web types are unchanged, and there is no migration. The change reaches a request only through a solve that hits one of these paths: the `run_optimizer` tool output that goes into the next planner request, and the Explainer's and Critic's inputs. The PR lists the cassettes that miss in a full offline replay. They are re-recorded in the main session with the owner's OK.
- **Timing.** The check runs only after phase 1 runs out of work short of a target. On clear-curd it proves infeasibility in about 0.6 s. The greedy plan runs only after the main solve finds nothing, and takes under a second.
