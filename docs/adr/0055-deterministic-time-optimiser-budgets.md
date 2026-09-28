# Each optimiser phase stops on a CP-SAT deterministic-time budget, with wall-clock limits only as safety nets, so a plan never depends on the machine

Until now every CP-SAT limit was wall-clock time (`max_time_in_seconds`). This covered:

- the closest plan to the clearance targets;
- the main solve;
- the binding-analysis re-solves;
- the relaxation.

A solve that hits its limit therefore ends in a different place on a slower or busier machine. #51's decision gate measured this on the seed-42 world, with the `make train` models:

- **Demo brief** (₹8 lakh, 400g namkeen at 60%). The main solve got `max(10 − elapsed, 5)` wall seconds after building the problem and the closest-plan phase, which was 7.8 s against the 4 s it needs.
  - With the limits halved, as on a machine about 2× slower, it returned FEASIBLE: 17 of its 40 lines differed, the objective fell from ₹1.78 lakh to ₹1.58 lakh, and the proven binding constraints went from 6 to none.
  - Under a 12-process CPU load it found no plan at all in time.
- **e2e brief** (₹2 lakh). With more margin it stayed stable when halved, but under load it returned FEASIBLE at the 10 s cap.
- **Binding analysis.** Its re-solves always ran to their slice of the 8 s. A faster machine could prove a constraint binds where a slower one could not.

The plan's numbers are what the Critic's and Explainer's requests contain. So #51's full-graph cassettes (ADR 0054) would replay only on a machine like the recording one, and a plan depended on machine load. Issue #133; option (a) of #51's gate, chosen with the owner.

## Decision

- **Each phase stops on CP-SAT's deterministic time** (`max_deterministic_time`), a count of work done that is the same on any machine for the same model, seed and OR-Tools build. A search that runs out of budget ends in the same place everywhere.
  - Workers stay at 1. With more workers, `interleave_search` keeps the search deterministic (ADR 0036).
- **The budgets:**
  - `OPTIMIZER_DETERMINISTIC_LIMIT=10` per solve. With clearance targets, the closest plan takes up to half. The main solve gets what the closest plan left, at least half. Both amounts are counted in deterministic seconds, not in elapsed time.
  - `OPTIMIZER_BINDING_DETERMINISTIC_LIMIT=6` for the binding analysis (ADR 0038). The budget shrinks by each re-solve's own `deterministic_time`, not by a monotonic deadline. Each re-solve gets an even share of what is left, as before.
    - 6 is the work today's 8 wall seconds bought on a quiet machine: 5.7–6.2 deterministic seconds on the e2e and demo briefs.
    - With it, the e2e brief keeps its 3 proven binding constraints and the demo keeps its 6.
    - `0` still turns the analysis off. The `relax_constraints` tool and the speed test use this.
  - `OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT=10` for the relaxation (ADR 0044). The first re-solve takes up to half, and the second what the first left, at least half.
- **Wall-clock limits remain, only as safety nets:** `OPTIMIZER_TIME_LIMIT_SECONDS=60`, `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS=30` and `OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS=60`.
  - Each is about 4–6× what its budget takes on a quiet development machine, where one deterministic second takes about 1.3 wall seconds.
  - A machine that reaches a net is badly overloaded. The phase then ends where the net stopped it, so determinism is lost only there.
  - The binding analysis's swap phase needs no CP-SAT work. It is still guarded by both.
- **Recorded as settings.** `SolverSettings` gains `deterministic_limit`, `binding_deterministic_limit` and `relaxation_deterministic_limit`, and `Planning.solver` exposes the settings built from the environment. #51 adds the three budgets to the settings a cassette manifest records (ADR 0054 D11).
- **We rejected:**
  - Keeping time-dependent fields out of what the LLM sees. A main-solve timeout changes the plan itself, not only its status.
  - Raising the wall-clock limits. That widens the margin but stays nondeterministic under load, and adds seconds to every binding analysis.

## What this amends

- **ADR 0036:**
  - "OPTIMIZER_TIME_LIMIT_SECONDS=10 (wall clock)" is now a 60 s net behind a 10-deterministic-second budget.
  - "The same input gives the same plan whenever the solver proves optimality within the limit" now holds always, whether or not the budget runs out.
  - The rejection of the deterministic time limit ("its units are not seconds, so under 10 s would not be guaranteed") is reversed. The wall-clock guarantee is given up for reproducibility; the demo solves prove optimality after about 3 deterministic seconds.
- **ADR 0038:** the binding analysis has its own deterministic budget (6), not an 8 s wall-clock limit. Which constraints are settled, and how, no longer depends on the machine.
- **ADR 0039:** the 10 s budget for `solve` is still measured in wall seconds by the `model`-marker speed test. It still passes: the demo's solve proves optimality well inside its work budget, about 6–7 s in all here. Under heavy CPU contention the solve is no longer cut off at 10 s, so it takes longer rather than returning a worse FEASIBLE plan. The test's fastest-of-two-runs rule stays.
- **ADR 0044:** "a timeout is never reported infeasible" holds for a budget that runs out, and now reproducibly. Both relaxation re-solves share the deterministic relaxation budget.

## Consequences

- On a quiet machine the plans are unchanged. The e2e brief gives 35 lines, ₹172,384, OPTIMAL, with the same 3 proven binding constraints. The demo brief gives 40 lines, ₹178,194 (₹1.78 lakh), OPTIMAL, with the same 6. Their Explainer plan data is identical to before.
- Under a 12-process CPU load both briefs now give that same plan. Before, the demo found no plan and e2e returned a FEASIBLE one.
- **Timing.** On a quiet machine the default sequence takes about the same (e2e 28 s, demo 31 s against 26–28 s before). The binding analysis spends about as much work as before. On a slower or busier machine planning takes proportionally longer instead of ending early: both briefs took about 60 s under the 12-process load. SPEC §6's 60 s session target is measured in E9 on a normal machine.
- **Tests:**
  - with every budget too small to finish, a run ends in the same place whatever its wall-clock nets (synthetic, and the constrained demo brief);
  - the demo's binding analysis is the same with its nets 10× longer;
  - the settings are validated and read from the environment.
- There is no migration and no API contract change. `.env.example` and the README list the new settings, and compose sets none of them.
