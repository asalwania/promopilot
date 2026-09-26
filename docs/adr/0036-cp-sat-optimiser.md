# The CP-SAT optimiser selects from positive-value options, charges exact pairwise terms, and runs single-threaded with a fixed seed

E6 (#34) adds `solve` and the `run_optimizer` tool (SPEC §9.4). The spec gives the variables, the objective and the constraints. It leaves open:

- which options the solver may select;
- how the pairwise terms are priced and linearised;
- how rupees become the integer paise CP-SAT needs;
- how the solver stays deterministic;
- what the tool returns;
- how the "tighter budget gives shallower depths" property (F-03 AC1) can hold at all.

We chose these with the owner:

- **Only options worth at least one paisa alone are eligible.** An option's `value` is incremental profit − cannibalisation + halo + clearance value (ADR 0035). It must round to at least one paisa. This is F-01 AC1 read directly: every plan line pays for itself, or is a clearance SKU whose clearance value justifies it.
  - A pairwise gain cannot make a negative-value option eligible.
  - We rejected admitting every option with a "positive net of its pairwise terms" constraint. On the demo brief that brings back about 196,000 option pairs.
- **Eligible options must also keep every per-line rule.** Candidate generation already prunes them, but hand-built candidate sets need not. So the solver checks them again:
  - P90 units within available stock, and a BUNDLE partner's within its own (ADR 0004, ADR 0014);
  - the line inside the promo window;
  - no deeper than the maximum discount;
  - no SKU below unit cost unless it is overstocked (ADR 0007).
- **The model** (integer paise):
  - maximise Σ x_o · value_o − Σ y_ij · pairwise_ij;
  - at most one x per (SKU, region) that the option occupies, a BUNDLE partner included (ADR 0014);
  - at most the company-policy number of promoted SKUs per category per region, a partner counting in its own category (ADR 0028);
  - Σ x_o · promo_cost_o ≤ marketing budget;
  - Σ x_o · (m · revenue_o − gross_profit_o) ≤ 0, where m = max(the request's minimum margin, the policy margin floor) (ADR 0007).

  Costs and margin shortfalls are rounded **up** to whole paise and the budget **down**. Every plan the solver accepts therefore passes `validate_plan` (ADR 0012). Values and pairwise terms are rounded to the nearest paisa.
- **Pairwise terms are exact, per option pair, with no cap.**
  - Pairs are the eligible options in one region that share no SKU and share a week and a target segment.
  - Their `pairwise_cannibalisation` (ADR 0033) comes from a new batch function, `pairwise_cannibalisations`. It makes one `line_paths` call and one baseline forecast per region, so 2,000 demo pairs take about 3 s instead of 0.28 s each.
  - A pair with a non-zero term gets y_ij = x_i ∧ x_j, enforced both ways. So a negative term, a gain, is credited too, not just a positive one charged.
  - We rejected a constant per SKU pair, as ADR 0033 did.
- **Deterministic solver settings, in config:**
  - `OPTIMIZER_TIME_LIMIT_SECONDS=10` (wall clock), `OPTIMIZER_WORKERS=1`, `OPTIMIZER_SEED=0`.
  - `solve(..., seed=...)` takes the seed explicitly.
  - With more than one worker, `interleave_search` keeps the search deterministic.
  - The same input gives the same plan whenever the solver proves optimality within the limit.
  - If the limit runs out first, the status is `FEASIBLE` with the best plan found, which may differ between machines. If no plan was found in time, the result is the empty plan: it keeps every constraint #34 enforces.
  - We rejected CP-SAT's deterministic time limit, because its units are not seconds and "under 10 s" would not be guaranteed.
- **Inputs and outputs:**
  - The call is `solve(request, options, facts, policy, *, settings, seed)`.
  - `facts` is an `OptionFacts`: each SKU's category, prices and overstock flag in a region, and the pairwise terms of option pairs. The issue's `relations` argument became this protocol, so tests can pin both.
  - `FittedOptionFacts(context)` builds it from the `OptionContext` the options were generated in. A `CandidateSet` keeps its facts, so `run_optimizer` prices pairs on the same models even after a retrain.
  - The result, `OptimisationResult`, holds: status (`OPTIMAL | FEASIBLE | INFEASIBLE`), objective in rupees, the `PromoPlan`, the selected rows of the candidate table, the pairwise terms charged, and the eligible option and pair counts.
- **`run_optimizer`** takes a `candidate_set_id`. An id that was never stored, or has been dropped, is `invalid_input` telling the planner to call `generate_candidates` again. The output has:
  - the status and the objective;
  - each selected line with its units, P90 units, available stock, promo cost, revenue, gross profit, incremental profit, cannibalisation, halo, clearance value and value;
  - total promo cost against the budget;
  - the blended margin against the minimum margin applied;
  - the pairwise terms charged;
  - the candidate, eligible and pair counts.
- **The depth property is stated per (SKU, region).** F-03 AC1 says a lower budget or a higher minimum margin moves depths "in the expected direction". Across SKUs that is false. With A at 10% costing ₹10 (value 100) and B at 40% costing ₹50 (value 1,000):
  - at a ₹60 budget the plan is A + B, average depth 25%;
  - at ₹50 it is B alone, average 40%.

  So the hypothesis test uses one (SKU, region) whose options differ only in depth: deeper costs strictly more, earns a strictly lower margin, and no two values tie. There the property is provable, because the feasible set shrinks to shallower depths. We rejected a tie-break toward shallower depth (a second solve) and a budget sweep on a fitted world.
- **Left for #35:** binding constraints, the not-selected list and "why chosen" reasons. #36 adds clearance targets, regional caps and the KVI tolerance.

## Consequences

- Until #36, the empty plan is always feasible, so `INFEASIBLE` cannot happen yet. #36 must revisit the "no plan in time" case once clearance targets can make the empty plan infeasible.
- On the seed-42 demo brief (weeks 108–109, ₹2 lakh), the world as first generated had no option with positive incremental profit. Only 92 of 10,981 options were eligible, all clearance lines on two overstocked SKUs, and the optimal plan was 4 clearance lines worth about ₹11,248, found in under 0.1 s.
- After the world was retuned (ADR 0037, #109), 1,935 of 10,396 options are eligible, with 3,796 pairwise terms. The optimal plan has 35 lines, 21 of them without clearance, worth ₹172,384 for ₹199,909 of promo cost. The oracle scores it at +₹66,607 incremental profit. Solving takes about 18 s: about 14 s computes the pairwise terms, and CP-SAT takes about 4 s. That is above SPEC's 10 s optimiser budget, so the pairwise batch needs speeding up. The optimiser's logic is unchanged.
- OR-Tools is pinned to one exact version, so solver behaviour and determinism do not drift with an upgrade.
