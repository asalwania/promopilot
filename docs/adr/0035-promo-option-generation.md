# Promo options are enumerated in full, pruned before and after one batch prediction, and handed to the optimiser through an in-process store

E6 (#33) adds promo option generation (SPEC §9.3) and the `generate_candidates` tool. The spec says what to enumerate and prune. It does not say how fast generation must be, how P90 is computed, how a BUNDLE partner's numbers and cost split are reported, what the tool returns to the LLM, or what the optimiser (#34) consumes. We chose these with the owner:

- **The full grid, with no cap.** For each in-scope (SKU, region), the grid covers every mechanism, depth, duration, start week and target segment:
  - Depths are mechanism-appropriate (ADR 0005), matching the promo history: PCT_OFF and FIXED_PRICE use 5, 10, 15, 20, 25, 30, 40 and 50%, BOGO uses 50% only, and BUNDLE uses 10–25%.
  - A BUNDLE is enumerated with every detected complement as its partner, in scope or not (ADR 0014).
  - Every duration of 1–4 weeks is tried at every start week that keeps the line inside the promo window.
  - Targets are the four segments and All customers (ADR 0006).

  On the seed-42 demo brief (Snacks and Beverages, North and West, Diwali weeks 108–109), that is 28,980 options. We rejected keeping only the top K options per SKU and region, because the pairwise terms mean such a cap can drop the optimum. We also rejected a coarser depth grid. If the solver needs fewer options, #34 decides the reduction.
- **Prune before predicting, and count the first failing reason.** Price rules do not depend on timing or target, so they are checked once per SKU, region, mechanism, partner and depth, before any prediction. They apply in this order:
  1. `no_charm_price`: a FIXED_PRICE depth price below ₹9. It cannot happen on the seed-42 world, where the cheapest SKU is ₹20.
  2. `max_discount`: the effective discount is above the company-policy maximum, so a charm price counts (ADR 0015).
  3. `below_cost`: the anchor, or a BUNDLE partner, sells below unit cost and is not overstocked in the region (ADR 0007).
  4. `duplicate_price`: a FIXED_PRICE depth lands on a charm price a shallower depth already offers.

  The survivors are predicted in one batch. Then two stock rules apply:
  - `stock`: the anchor's P90 units exceed its pooled available stock (ADR 0004).
  - `partner_stock`: a BUNDLE partner's P90 units exceed its own available stock (ADR 0014).

  Each pruned option counts once, under the first rule it breaks. Minimum margin and the budget stay plan-level (ADR 0007).
- **Overstocked** here means the days-of-cover flag from the pooled inventory (ADR 0032). Brief-named clearance SKUs join the flag when the planning request carries them (#36).
- **P90 = mean + 1.2816 × std**, the normal approximation to `predict`'s units. We rejected the negative binomial quantile, which needs the dispersion outside the demand model for a small difference at these unit counts. The E7 simulator reports its own sampled P90.
- **The demand model reports a BUNDLE partner's numbers.** `Prediction.options` gains `anchor_discount_funding`, `partner_units`, `partner_units_std`, `partner_baseline_units` and `partner_discount_funding`. They are 0 without a partner.
  - The partner's std comes from the same delta method and noise as the anchor's (ADR 0024).
  - Discount funding is split per SKU, each at the depth off its own base price. That is the pair's discount split pro-rata by base price (ADR 0005, ADR 0014).
  - Anchor funding + partner funding + fixed marketing cost = `promo_cost`.
  - `estimate_demand` keeps its output unchanged.
  - We rejected taking partner units from `line_paths` and estimating the partner's std from the anchor's, which would be a made-up spread.
- **Clearance value is what the oracle counts** (ADR 0005, ADR 0017). For the anchor, and a BUNDLE partner, that is overstocked in the line's region, it is (promo-week units − promo-week baseline)⁺ × unit cost × the write-off rate, on expected units.
- **Cannibalisation and halo are the single-line figures (ADR 0033), in one batch.** `line_effect_totals` in `promopilot.models.relations` returns each line's summed `line_effects` for tens of thousands of lines at once:
  - the baseline is forecast once per region and cumulated over weeks;
  - lines that cut the same SKUs to the same prices share their price shifts;
  - each SKU's relations are looked up once.

  Pairwise terms are left to #34, which calls `pairwise_cannibalisation` only for pairs it needs.
- **The demand model forecasts each distinct baseline row once.** A batch of options repeats the same store × SKU × segment × week many times. `_Baseline.predict` now de-duplicates rows before LightGBM and scatters the results back. The numbers are identical.
  - On the demo brief, prediction for all 28,980 options fell from 36 s to 8 s.
  - End-to-end generation (price pruning, prediction of the ~17,400 survivors, stock pruning, effects and clearance) takes about 7 s. It keeps 10,988 options.
  - SPEC's budgets are 60 s for a full plan and 10 s for the optimiser.
  - Superseded in part by ADR 0087 (#113): each store-invariant response term is computed once per option, SKU, week and segment, and every number is unchanged.
- **`PromoOptions` is what the optimiser consumes.** It is a frozen dataclass:
  - `lines`: a tuple of `PlanLine`.
  - `table`: a DataFrame with one row per line, in the same order. Its `TABLE_COLUMNS` are the demand model's option columns plus `p90_units`, `available_stock`, `partner_p90_units`, `partner_available_stock`, `cannibalised_profit`, `halo_profit`, `clearance_value` and `value`. `value` is incremental profit − cannibalised + halo + clearance value, the option's worth if it runs alone.
  - `enumerated`: every option enumerated, kept or pruned.
  - `pruned`: the count for every `PruneReason`.

  We rejected a list of pydantic objects per option. It is slower to build and to turn into solver coefficients.
- **`generate_candidates` returns a summary and stores the full set.**
  - The input is a `PlanningRequest`, plus optional `mechanisms`, `target_segments` and `sku_ids` (within the request's scope).
  - The request's as-of week must equal the tool's bound as-of week (ADR 0032), so the LLM cannot move the clock.
  - The output has:
    - a `candidate_set_id`;
    - the demand and relations model versions and the as-of week;
    - the enumerated and kept counts;
    - pruned counts per reason;
    - counts per region and mechanism;
    - the top 20 options by value, each with its plan line, units, P90 units, available stock, promo cost, incremental profit, cannibalisation, halo, clearance value and value.
  - The full set goes into a `CandidateStore` (`promopilot.optimizer`). It is an in-process store of the 16 most recently used sets, keyed by id, and `run_optimizer` (#34) reads from it. The API keeps one on `app.state.candidates`.
  - Errors:
    - a missing demand or relations model is `model_unavailable`;
    - missing data is `data_unavailable`;
    - an as-of mismatch, an unknown category or region, a SKU outside the scope, or an option the model cannot predict is `invalid_input`.
  - We rejected returning every option, which would never fit an LLM context. We also rejected binding the request to the tool per session, because the registry is built once at startup.

## Consequences

- #34's `run_optimizer` takes a `candidate_set_id`, gets the `CandidateSet` (`candidate_set_id`, `request`, `options`) from the store, and builds its variables from `options.lines` and `options.table`. An id that has been evicted, or that belongs to another process, must be regenerated.
- A restart empties the store, like the background planning tasks (ADR 0020).
- The planning request does not yet carry clearance targets. When #36 adds them, brief-named SKUs must also count as overstocked here.
