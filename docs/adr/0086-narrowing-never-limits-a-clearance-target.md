# Narrowing candidates never limits a clearance target; the demo brief plans feasibly, and accepting a relaxation moves to an infeasible session

#142 comes from the E8 exit review (#10). The demo brief (SPEC §3.2) ended `INFEASIBLE` in every round: SKU0006, a 400g namkeen pack, reached 59.87% of its 60% clearance target in the North. So the demo opened on a plan the manager could not approve, and ADR 0070 had to accept a relaxation of 0.14 points before approving.

The ticket asks for one fix after #58's target review, with AG-06 kept by a separate infeasible scenario. SPEC and the ADRs leave open:

- what causes the shortfall, and so which fix;
- whether the fix covers target segments only, or mechanisms too;
- where the accept-relaxation journey (ADR 0070, ADR 0076) goes once the demo is feasible;
- which scenarios keep AG-06;
- the merge order with #159, #141 and #165.

We chose these with the owner (D1–D6 on #142; every recommended option).

## What the gate measured

The gate ran offline with no LLM, on the seed-42 world (`EvalWorld.generated(42)`, as-of week 104, models fitted in memory). It read the brief with the rules (the same request the LLM reads: North and West, Snacks and Beverages, weeks 108–109, ₹8 lakh, 18%, 60% on SKU0002 and SKU0006), then solved with the session's work budgets and seed 0.

- **The planner narrows to Families.** "Target families" makes the planner call `generate_candidates` with `target_segments: ["Families"]` in every round (the demo's cassettes). A segment-exclusive offer sells only that segment's units (ADR 0006).
- **One Families line cannot clear SKU0006 in the North.** Its stock is 926 units and its baseline over the window 172.6 (18.6%). The best Families line adds 381.8 units, which gives 59.87%. With one line per SKU and region, that is the most any plan reaches: 1.23 units short. Policy binds, and the proven relaxation lowers the target to 59.86%, as recorded.
- **Unnarrowed, every revision is `OPTIMAL`.** The best line open to All customers takes SKU0006 North to 86.5%.

| Revision | Families only | Not narrowed | Families, clearance SKUs spared (this ADR) |
|---|---|---|---|
| 1 (₹8 lakh) | INFEASIBLE, ₹31.6k | OPTIMAL, 40 lines, ₹176.7k | OPTIMAL, 22 lines, ₹59.6k |
| 2 (₹6 lakh) | INFEASIBLE, ₹31.6k | OPTIMAL, 40 lines, ₹176.7k | OPTIMAL, 22 lines, ₹59.6k |
| 3 (North) | INFEASIBLE, ₹16.5k | OPTIMAL, 20 lines, ₹82.8k | OPTIMAL, 11 lines, ₹30.1k |

- **#159's safety margin (ADR 0080) does not change it.** The best Families line is not cut by its 2σ stock buffer, so the Families plans still stop at 59.87%. The budget is far from binding. Unnarrowed under #159, SKU0006 North's ceiling falls to 79.5%, still above 60%. With this ADR's rule, #159's branch plans the same `OPTIMAL` revisions.
- **Neither the data nor the budget is the cause.** Revision 3 spent ₹1.01 lakh of ₹6 lakh.

## Decisions

- **D1. `mechanisms` and `target_segments` never narrow a SKU the brief names for clearance.**
  - `optimizer.generate_options` gives each such SKU every mechanism and segment, on the full path and on the path that reads a narrowing off a generated set (ADR 0077). Every other SKU is narrowed as before.
  - `generate_candidates`' description says so. Its summary gains `not_narrowed`: the clearance SKUs a narrowing by mechanisms or segments left whole.
  - This completes ADR 0059 D1: a planner lever never puts a brief's clearance target out of reach. `exclude_sku_ids` refuses a clearance SKU, and #141 (ADR 0084 D4) refuses to limit one.
  - A BUNDLE anchored on another SKU, with a clearance SKU as its partner, is still narrowed with its anchor.
  - We rejected:
    - dropping "Target families." from the demo brief, which departs from SPEC §3.2 and leaves the cause for every other brief;
    - tuning the data;
    - counting a shortfall within a tolerance as met, which is arbitrary and contradicts ADR 0074 D2.
- **D2. Both levers, not target segments alone.** A mechanism narrowing can put a target out of reach in the same way, and one rule is simpler to state. We rejected refusing `target_segments` whenever the brief has clearance targets, which wastes planner steps and blocks a legitimate narrowing.
- **D3. The demo is amended twice and approved; a new session, `infeasible`, accepts a relaxation.**
  - The demo script is plan → "Budget cut to ₹6 lakh" → "Drop West" → approve revision 3. This amends ADR 0070 D1. An accept step there would now fail the recording (ADR 0070 D2): revision 3 has no relaxation.
  - The fifth session script, `infeasible`, is `infeasible-clearance-tiny-budget`'s brief: 95% of the 400g namkeen stock on ₹10k, planned, its relaxation accepted and approved.
    - Offline, revision 1 is `INFEASIBLE`. The relaxation raises the budget to ₹10,043.06 and lowers SKU0002's target to 40.83% and SKU0006's to 36.78% (proven, policy binds).
    - Accepted and re-planned, it is `OPTIMAL` with 2 lines.
  - `infeasible` is not a home-page example: the four examples are unchanged. The demo example's hint drops "accept the relaxation".
  - The Playwright amend journey is split. `amend.spec.ts` plans the demo, checks each revision is feasible with a passing clearance check, amends twice and approves revision 3. `infeasible.spec.ts` checks the infeasibility panel, accepts, and approves revision 2. This amends ADR 0070 D6 and ADR 0066 D11.
  - We rejected dropping the end-to-end accept journey, which leaves AG-06 visible only in component tests. We also rejected a demo amendment that makes the plan infeasible again, which is contrived for the demo story.
- **D4. AG-06 stays with the `infeasible_constraints` scenarios.**
  - They already expect INFEASIBLE, a relaxation and a binding constraint.
  - `demo-budget-cut-drop-west` drops its accept. It expects a feasible revision 3, `meets_clearance` for SKU0002 and SKU0006 at 60%, `excludes_region: West` and `diff_changes: scope.regions`. This amends ADR 0076 D4.
  - A new `mid_plan_amendments` scenario, `infeasible-tiny-budget-accept`, takes the tiny-budget brief and accepts revision 1's relaxation. It expects a feasible revision 2 meeting its relaxed targets, with `diff_changes: clearance_targets`. It replays the app's `infeasible` session, as ADR 0076 D7 has the demo do. The suite is 33 scenarios, with 4 mid-plan amendments.
- **D5. Merge order: #165 → #159 → #141 → #142.**
  - #142 lands last.
  - The main session then records the app sessions, the new `infeasible` one included, and then the full scenario suite, with the owner's OK. So the accept round is recorded once, under #165's acceptance in code.
- **D6. This PR records nothing** (ADR 0054 D10). The PR lists the checks expected red until the recording.

## Consequences

- **New public names:** `GenerateCandidatesOutput.not_narrowed`.
- **LLM requests:**
  - `generate_candidates`' description and input schema reach every planner request, so every planner cassette misses.
  - Every session whose planner narrows a request with clearance targets gets other candidate sets and plans from the first `run_optimizer` on, so its later planner, Critic and Explainer requests miss too.
  - The demo's accept round (its cassettes after revision 3) is no longer called. The manifest lists the `infeasible` session only once it is recorded.
- **Expected red until recording:**
  - the committed-cassette tests (`manifest_problems`, and the Context replay of the new session);
  - the images job's `--check`;
  - the Playwright demo and infeasible journeys;
  - an eval replay of the demo and the new scenario.
- **Recording** (Git Bash, a live key, after `make data` and `make train`): `make record-cassettes`, then `make check-cassettes`, then `make record-eval-cassettes` and `make eval`.
  - If the `infeasible` accept round runs to the Critic's cap, `("infeasible", 1)` stays in `ROUNDS_AT_CAP`; otherwise drop it.
- There is no migration, no API contract change, no new setting and no prompt change. SPEC §3.2 is unchanged.
- **This amends:**
  - ADR 0059 D1 (narrowing, not only leaving out, spares a clearance target);
  - ADR 0070 D1 and D6 (the demo script and journey);
  - ADR 0076 D4 (the demo scenario's expectations);
  - ADR 0065 D8 (a fourth mid-plan amendment that accepts a relaxation).
