# The simulation card charts each plan line's P10–P90 band and P50 and re-simulates a plan awaiting a decision against a competitor reaction; a competitor card shows the KVI gaps in scope, the plan line promoting each, and the planner's response kept on the explanation

E10 (#63) helps managers understand risk and competitor handling (F-08, F-09, SPEC §11). It needs:
- a Recharts chart with a P50 line and a P10–P90 band;
- a control to re-simulate with a competitor reaction;
- a competitor panel showing gaps, undercut KVIs and the planner's response.

The read model already carries most of this:
- `plan_revision.simulation` is the stored `PlanSimulation`. It has P10/P50/P90 ranges per plan line and for the plan, stock-out risk per region, and its `competitor_reaction` (ADR 0042, ADR 0045).
- `POST /api/plans/{id}/simulate` re-simulates the latest revision, stores the result in place of the old one and answers with it. It returns 409 for an approved session (ADR 0043, ADR 0045).
- `useCompetitorGaps` holds the KVI gaps at the request's as-of week (ADR 0060 D10).

Three things were missing:
- The simulator keeps no per-week series, so the chart has no time axis.
- The planner's response to undercut KVIs (ADR 0049 D4) was stored only inside the summary's text.
- The frontend schema did not read `competitor_reaction`.

Re-simulating makes no LLM call: `PlanService.simulate` reads the session, simulates and saves.

We chose these with the owner (D1–D9 on #63, every recommended option).

## Decisions

- **D1. The chart has plan lines on its x-axis.** Each plan line, labelled "SKU · Region" in plan order, is one point. A P10–P90 band (a Recharts range `Area`) has the P50 `Line` through it.
  - A metric toggle picks gross profit (the default), units or promo spend.
  - A region filter (all regions, or each region with lines) keeps a 35-line plan readable.
  - A **Plan totals** strip gives P50 with its P10–P90 range for gross profit, units, revenue, promo spend, margin and sell-through, plus each region's stock-out risk.
    - The totals come from `simulation.total`, never from adding lines up, because plan ranges are percentiles of each run's sums (ADR 0042).
  - Every number names `simulate_plan`, with the percentile, runs and seed, through `SourcedNumber`.
  - `recharts` (v3) joins the frontend's dependencies, as SPEC §7.5 names it.
  - We rejected promo weeks on the x-axis. That needs a new weekly-percentile series from the simulator, and older simulations would have none. We also rejected floating range bars, which are not the "P50 line and band" that SPEC §11 asks for.
- **D2. The chart is tested through its values, not its SVG.**
  - The figure is labelled "Simulated gross profit by plan line" (or the metric chosen), with an HTML legend: "P10–P90 band" and "P50".
  - **Show values** opens a "Simulated ranges" table with each line's P10, P50 and P90, which the chart draws.
  - Vitest asserts on the figure, the legend and that table, never on Recharts' SVG. The chart itself is `aria-hidden`.
- **D3. A stress test sits in the simulation card.**
  - "Competitor match probability" is a select of No reaction, 25%, 50% (the default) and 100%, with a **Re-simulate** button.
  - `n_runs` is omitted, so the server uses `SIMULATION_RUNS`.
  - While it runs, the button reads "Re-simulating…" and the control is disabled.
  - A failure shows "Couldn't re-simulate: <the API's detail>". A 409 also reloads the session.
  - The control shows only while the session is `awaiting_approval` or `rejected`, the statuses that accept a decision:
    - an approved plan is final (ADR 0066), and the API refuses it;
    - while planning, the revision on screen is about to be replaced;
    - a failed session has no revision.
- **D4. `simulatePlan` and `actions.simulate`.**
  - `simulatePlan(sessionId, matchProbability | null)` in `lib/api/sessions.ts` posts `{competitor_reaction: {match_probability} | null}`.
  - It answers `SimulateResult`: `{ok: true, revisionNumber, simulation}` or `{ok: false, reason, conflict}`, because the endpoint returns a simulation, not a session.
  - `SessionActions` gains `simulate: Simulate`, which returns an `ActionOutcome` like the other actions (ADR 0066 D9).
  - `SessionView` puts the new simulation into the cached session's revision when the revision number matches, so the plan table's P10–P90 and stock-out columns show it at once. On a conflict, it reloads.
- **D5. A re-simulation replaces the shown one, labelled by its competitor reaction.**
  - The API stores one simulation per revision (ADR 0043, ADR 0045).
  - The card reads "No competitor reaction", or "Stress test: the competitor matches each plan line's discount with probability 50%".
  - While a stress test is stored, the plan tabs open with "Profit ranges and stock-out risks below are from the stress test: …".
  - Choosing **No reaction** re-simulates the plain one. With the seed fixed, it is exactly the simulation planning stored (ADR 0045 D5).
  - The UI never says "scenario", which belongs to evals (CONTEXT.md).
  - We rejected keeping the previous simulation in the browser to draw beside the new one, which a reload loses. We also rejected storing both on the backend, which changes ADR 0043's contract.
- **D6. The competitor card lists the KVI gaps in the brief's scope.**
  - The gaps come from the shared `useCompetitorGaps` query (one request with the plan's undercut callouts).
  - They are filtered to the request's regions, categories and SKUs, which are the gaps the planner read (ADR 0049 D4). Undercuts come first, then the API's order.
  - The "Competitor gaps" table has these columns: SKU and name, Region, Our price, Competitor price, Gap, CPI, Flags (Undercut, On promo) and Plan line.
  - Plan line is the line promoting that SKU in that region, as anchor or as a BUNDLE's partner, shown as mechanism and depth; otherwise it reads "Not promoted". This is a lookup: whether a price matches is not worked out in the browser.
  - Numbers name `get_competitor_gaps` with the price week, and the depth names `run_optimizer`.
  - The card handles loading, error-with-Retry and "No KVI in scope has a competitor price." states.
- **D7. The planner's response is kept on the explanation.**
  - `PlanExplanation.competitor_response: tuple[str, ...] = ()` holds the sentences `CompetitorGaps.undercut_response` writes, without the degraded-planning note.
  - They flow from `PlannerAgent.explained` through `PlannedRevision.competitor_response`, `PlanAttempt`, and `PlanningState.competitor_response` (cleared by an amendment, like the planner notes). The graph's Explainer node copies them onto the explanation.
  - They still open the summary as planner notes (ADR 0050).
  - The field lives in the `plan_revisions.explanation` JSONB, so no migration is needed.
  - The Explainer's LLM request does not change (its view and `ExplainerAnswer` are untouched), so every recorded session still replays (`python -m promopilot.cassettes --check`).
  - Explanations stored before this read back with none. The card's "Planner's response" section then says "The plan summary gives the planner's response." With no undercut in scope, it says "No KVI in scope is undercut, so the plan answers none."
  - We rejected parsing the sentences out of the summary, which ties the UI to backend wording. We also rejected showing no response, which falls short of F-08.
- **D8. Both cards come after the plan's checks and before the audit trail**: Competitor prices first, then Simulation.
  - `SessionDetails` takes `competitorPrices` (the gaps with their loading state), next to `competitorGaps`.
  - The simulation card is keyed by the revision number, so a new revision starts afresh.
  - Both show on a final session, where the simulation is read-only.
- **D9. Playwright extends two existing journeys on existing cassettes; no new recording.**
  - `brief-to-plan.spec.ts` (the `e2e` session) checks:
    - an Undercut flag in Competitor gaps;
    - the planner's response, which matches the stored `competitor_response`;
    - the chart and its values table.
  - It then re-simulates at 50% and checks the stress-test label and, through the API, the stored `competitor_reaction`.
  - `approve.spec.ts` checks that the final plan keeps its chart and offers no Re-simulate.
  - No planning run is added.

## Consequences

- New frontend modules:
  - `components/simulation-panel.tsx`: `SimulationPanel`, `Simulate` and `reactionLabel`;
  - `components/simulation-band-chart.tsx`: `SimulationBandChart`;
  - `components/competitor-panel.tsx`: `CompetitorPanel` and `CompetitorPrices`;
  - in `lib/api/sessions.ts`: `simulatePlan` and `SimulateResult`.
- `PlanExplanation`, `PlannedRevision`, `PlanAttempt` and `PlanningState` gain `competitor_response`. The OpenAPI and generated types change. There is no migration and no new recording.
- The first Recharts render in a Vitest file can take seconds on a busy runner. The suites that render the chart use a 15 s timeout, as the drawer's does.
- A stored stress test also changes the plan table's ranges until a plain re-simulation, and it is what an approval then approves. The card's label and the plan's note say so.
