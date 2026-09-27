# Every plan revision is simulated: one term draw per SKU and run, negative binomial noise per store, units capped at pooled regional stock

E7 (#39) adds the Monte Carlo simulator (SPEC §9.5, F-06 AC3, F-09) and the `simulate_plan` tool, and simulates every plan revision after optimisation. The issue fixes the metrics, the pooled stock cap and the acceptance tests. It left six questions open. We chose these with the owner:

- **Stock-out per line and per region; no per-store figure.**
  - A line's stock-out probability is the share of runs in which demand for its anchor, or for a BUNDLE's partner, reached that SKU's pooled available stock in the region.
  - A region's probability is the share of runs in which at least one of its plan lines ran out.
  - This amends ADR 0004 and SPEC §9.5, which promised a per-store stock-out probability as a risk signal. Stock is pooled across a region's stores and can be rebalanced between them (ADR 0004), so a per-store figure would need a store split of stock that nothing else uses. We rejected adding it next to the region figure, and also dropping the region figure.
- **A stock-out means demand reached the stock (demand ≥ available stock).** A line with no stock is therefore always out of stock, including in a run where it sells nothing. We rejected "demand exceeds stock", under which a zero-stock line is not out of stock whenever a run draws no demand.
- **Every term is sampled, α included: once per SKU and run.** Each run draws every promo response term of every SKU from N(estimate, std error): α, β per segment, γ, μ per mechanism and φ. The same draw applies to all of that SKU's regions, stores, weeks and segments, because parameter uncertainty is shared, not independent per row.
  - This keeps the simulated spread in line with `predict`'s delta-method std, which includes α (ADR 0024). ADR 0024's consequence listed only β, γ, μ and φ, and we rejected that narrower reading.
  - φ is drawn around its floored estimate with its unfloored standard error, so a run may draw a small negative φ (ADR 0037).
- **Each plan line is simulated on its own SKUs, with no cross effects between lines.** A line's demand is `predict`'s for that line alone (ADR 0017's attribution): the anchor and a BUNDLE's partner. Sampled θ does not move other lines' SKUs. The issue's metrics are all a line's own figures, and P50 then converges to the plan line's expected units. We rejected a joint simulation with sampled cross effects, which needs relations sampling and is not asked for.
- **100 ≤ n_runs ≤ 5,000, 1,000 by default.** The tool accepts runs in this range, and #40's endpoint will too. `SIMULATION_RUNS` must lie inside it. 5,000 runs of a 100-line plan take about 4.5 s. We rejected 10,000 as the ceiling.
- **The seed is configuration.** `SIMULATION_SEED` (default 0) and `SIMULATION_RUNS` (default 1,000) are bound to the planning session and to the `simulate_plan` tool, like `OPTIMIZER_SEED`. Neither the LLM nor the API sets the seed, so the same plan always simulates the same way. We rejected a seed derived per session, and an optional seed on the tool.

The details below follow from those choices and from SPEC:

- **One run.** For each store × segment × promo week of a line's SKUs, mean = store baseline × exp(Σ covariate × sampled term). Units ~ NegativeBinomial(size, size / (size + mean)), with the SKU's fitted size (ADR 0024).
  - Only promo weeks are simulated. The pull-forward weeks change none of the issue's metrics.
  - `DemandModel.response_rows(options, context)` gives the simulator these inputs as `ResponseRows`:
    - one row per option, SKU, store, segment and promo week, with its price, base price, unit cost and baseline;
    - each row's covariate per term;
    - each SKU's estimates, standard errors and negative binomial size.

    At the estimates, the rows sum back to `predict`'s units and money. The sampling itself stays in `promopilot.simulator`.
- **The stock cap is the oracle's (ADR 0011, ADR 0017).** Within a run, each of a line's SKUs sells at most its pooled available stock over the line's promo weeks. Available stock is on hand minus safety stock, clamped at 0. A SKU with no stock row has none. Revenue, gross profit and discount funding scale down with the units sold.
- **Metrics, as `LineOutcome` defines them (ADR 0017):**
  - units and sell-through are the anchor's;
  - revenue, gross profit and promo spend include a BUNDLE's partner;
  - promo spend is discount funding on the units sold plus the fixed marketing cost (ADR 0005, ADR 0015);
  - margin is gross profit over revenue within a run, and 0 in a run with no revenue;
  - sell-through is units sold over available stock, and None when there is no stock.
- **Plan totals are percentiles of each run's sums**, not sums of line percentiles. Plan sell-through is Σ anchor units sold ÷ Σ available stock, over the lines that have stock.
- **Percentiles** are numpy's interpolated 10th, 50th and 90th, made monotone with a running maximum so that p10 ≤ p50 ≤ p90 always holds. `Percentiles` validates the ordering.
- **Randomness** comes from one `numpy.random.default_rng(seed)`: the terms first, then the noise line by line in plan order. Arrays are vectorised over runs and store-segment-weeks.
- **Types.** `PlanSimulation` is a domain value type (ADR 0009) holding:
  - `n_runs` and `seed`;
  - `lines` in plan order, each with `sku_id`, `region`, the six ranges and `stockout_probability`;
  - `total`;
  - `regions` in Region order.
- **Sessions store the simulation.** `OptimisingPlanner` simulates plan revision 1 after `solve`, off the event loop, with the configured runs and seed. Migration 0006 adds `plan_revisions.simulation` (JSONB, nullable), and `GET /api/sessions/{id}` shows it as `plan_revision.simulation`.
  - Revisions from before the simulator read back with none.
  - A simulation failure fails the session like any other planning error: the plan's own demand model is simulated, so a failure is a bug, not a condition to hide.
- **`simulate_plan`** takes 1 to 200 plan lines and an optional `n_runs`.
  - The as-of week, stock snapshot, company policy and seed are bound.
  - The output has the demand model's id and version, the as-of week and the `PlanSimulation`.
  - Errors: a plan with a SKU twice in a region, a line before the as-of week, or a line the model cannot predict is `invalid_input`; no demand model is `model_unavailable`; no inventory snapshot is `data_unavailable`.

## Consequences

- On the seed-42 demo brief (35 lines), simulating 1,000 runs takes about 0.8 s. That adds under a second to the planning session's roughly 24 s, against SPEC's 60 s.
  - Plan P10/P50/P90: units 12,478 / 12,866 / 13,269 (expected 12,852), gross profit ₹445,224 / ₹463,112 / ₹481,098 (expected ₹462,936), promo spend ₹194,359 / ₹200,369 / ₹205,895 (expected ₹199,909).
  - Stock-out probability is 0.27 in North and 0.12 in West. The riskiest line runs out in about 10% of runs.
- A 100-line plan on the fitted seed-42 world simulates 1,000 runs in about 1.3 s.
- The `model`-marker speed test simulates 100 lines of the fitted seed-42 world at 1,000 runs, twice, and the faster run must be under 10 s. The world is now fitted once per test session (a `demo_context` fixture in `tests/conftest.py`), shared with the optimiser's speed test.
- P90 promo spend can exceed the marketing budget, which caps expected promo cost only (ADR 0005). The simulation reports it and the critic (E8) reviews it.
- #40 re-simulates a stored revision with the same `simulate` and bounds and replaces the stored result. #41 adds competitor reaction: it adjusts each run's γ covariate (log(cp / p) − log r) when the competitor matches, without changing this interface.
