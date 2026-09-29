# The performance pass reuses work within a session: one baseline forecast per region, a loop-back read off the first candidate set, each option pair priced once, and session time that ends with the session

#73 is E11's performance pass against SPEC §6: a full plan for 2 regions × 2 categories in under 60 s with a real LLM, the optimiser and the simulation each under 10 s, and under ₹20 of LLM cost per session. #73's decision gate profiled the demo scope: the seed-42 `diwali-snacks-beverages` scenario (Snacks and Beverages, North and West, weeks 108–109, ₹2 lakh). We chose these with the owner (D1–D10 on #73; every recommended option).

## What the profile found

- **Cost is within target.** The demo session costs ₹3.55 on `gpt-4.1-mini`: 9 calls, 82.7k input and 2.5k output tokens. Across the live recording of all 32 scenarios, the P50 is ₹3.04 and the most expensive (`demo-budget-cut-drop-west`, three revisions) is ₹10.73.
  - Planner: 6 calls, whose input grows from 5.1k to 17.8k tokens. The `run_optimizer` result is about 8.6k tokens of it.
  - Explainer: 17.1k tokens in and 1,834 out for 37 rationales. That is the largest single LLM wait, about 18–30 s estimated from its tokens.
  - Critic: under 800 tokens in. Context: about 2k in.
- **Latency is PromoPilot's own work, not the LLM.** Replayed with no network time, the demo's session still took 285.6 s on a loaded shared machine, where CP-SAT ran at about 4.2 wall seconds per deterministic second against ADR 0055's 1.3. So read the seconds below for their shares, not their size.
  - The Critic flags SKU0006 and SKU0035 as heavy cannibalisation, so the planner plans a second time. It calls `generate_candidates` with `exclude_sku_ids`, then `run_optimizer`. Each attempt repeats all of the work:

    | Step | Attempt 1 | Attempt 2 |
    |---|---|---|
    | `generate_candidates` (almost all demand `predict`) | 45.0 s | 32.4 s |
    | `run_optimizer`: pairwise terms and model set-up | 6.1 s | 4.7 s |
    | `run_optimizer`: main CP-SAT solve | 12.8 s (OPTIMAL at 3.02 det-s) | 4.8 s |
    | `run_optimizer`: binding analysis | 28.3 s (3 re-solves, each out of budget, nothing proven) | 30.7 s (6 re-solves) |
    | Revision: per-line cross effects (`line_effects`) | 28.0 s | 28.5 s |
    | Revision: simulation, 37 lines × 1,000 runs | 1.95 s | 1.9 s |

  - The Critic, the Explainer and the grounding checks take under 2 s in all.
  - The simulation is well inside its 10 s budget.
- **Session time counted scoring.** The runner stopped `session_s` only after scoring the plan and building the benchmarks (ADR 0063). So the first run of each distinct request also counted about 45 s of best-plan generation and solving. ADR 0062 defines session time as the time from the brief to the session's end.

## Decisions

- **D1. The revision's cross effects forecast the baseline once per region.**
  - `line_effects` forecast the no-promotion baseline once per plan line: 61 LightGBM forecasts for the demo plan. It now forecasts once per region, for every week any of the region's lines runs and every SKU any of them moves.
  - Each line then reads its own rows off that forecast, in the order a forecast of its own weeks and SKUs lists them. Each row's forecast does not depend on the batch, so every number is bit for bit the one-line figure. A test checks this on the fitted small world, as well as on hand-built fakes.
  - `Relations` indexes each SKU's substitutes and complements on its first lookup, instead of scanning every pair on each call. The index is never pickled, so registry artifacts are unchanged.
  - On the demo plan: 32.6 s → 1.4 s here.
- **D2. The Critic's loop-back reads its narrowed candidate set off the first one.**
  - `generate_options(..., unnarrowed=...)` takes the set generated for the same request in the same context with no narrowing. A narrowing by `exclude_sku_ids`, `sku_ids`, `mechanisms` or `target_segments` keeps or drops whole (anchor SKU, region, mechanism, target segment) groups. So the narrowed set is those rows of the unnarrowed set, and nothing is enumerated or predicted again.
  - `PromoOptions` gains a private tally: options enumerated, and pruned per reason, per such group. From it, `enumerated`, `pruned` and `pruned_by_mechanism` come out exactly as a narrowed generation counts them.
  - The request is validated as before, so the same `ValueError`s are raised. An empty narrowing list, or a set built by hand without a tally, generates afresh.
  - The `generate_candidates` tool looks up the id the same request would have had with no narrowing (ADR 0049's deterministic id). If that set is stored and was built on the live model objects, it reads the narrowed set off it. It also reuses that set's facts, so D3's priced pairs carry over. After a retrain it generates afresh.
  - The planner sees the same summary as before, and the candidate-set ids are unchanged. The rows' values are bit-identical in tests on the fakes and on the fitted small world, and on the demo brief's loop-back. A column the narrowing leaves all zeros, such as partner units without a BUNDLE, may keep the wider set's float type.
  - On the demo: 45 s → under 1 s for the loop-back's generation here.
- **D3. The facts price each option pair once.**
  - `FittedOptionFacts.pairwise_cannibalisation` keeps every term it has priced, per ordered pair of line objects. It tells lines apart by identity, as `pairwise_cannibalisations` does, and keeps each line so its id stays its own.
  - The terms are kept as sorted integer codes, a few MB for the demo's 259k candidate pairs. A later call prices only the pairs it has not seen.
  - The loop-back's set shares the first set's line objects and facts (D2), so its pairs are all already priced. That saves about 4 s here.
- **D4. Session time ends with the session, and the report shows the time waiting on the LLM.**
  - `session_s` now stops when the session ends, before its plan is scored and benchmarked.
  - Each run gains `llm_s`: the wall-clock seconds its LLM calls took, answered or not, measured by a wrapper around the eval's provider. It is near 0 under replay.
  - The P50 session time metric's breakdown gains `llm_p50_s` (whole seconds), and the Markdown's Agent behaviour table shows each session's LLM time.
  - `comparable()` leaves `llm_s` out, as it does `session_s`.
  - `RunResult` gains a field, so `make api-types` regenerated `docs/openapi.json` and the frontend's `schema.d.ts`.

### Left for later

- **D5. Binding analysis:** #168. Its re-solves would run concurrently, each on a fixed deterministic share, after #156.
- **D6. CP-SAT model:** #166 (opened by #156). It would link each pairwise variable one-sidedly, by the sign of its charge, after #158. #73's numbers are on that issue.
- **D7. Explainer latency:** no prompt change here. D4's `llm_s` measures it on the next live run. If the demo is still over 60 s, capping each rationale's length or explaining per region is ticketed. Either way, every Explainer cassette must be re-recorded.
- **D8. Cost:** no work. The P50 is ₹3.04–3.55 on `gpt-4.1-mini`. ADR 0049 estimated about ₹22 for a planning answered by the `claude-sonnet-5` fallback; that is unmeasured.
- **D9. Measurement:** after this merges, the main session runs `make eval ONLY=diwali-snacks-beverages RUNS=3` live on a quiet machine (no parallel agents), with the owner's OK, for P50 session time, P50 LLM time and cost. Any gap above 60 s is ticketed from that report.
- **D10. Faster first generation:** recorded on #113, which already covers speeding up `DemandModel.predict`. The rows would be shared across an option's five target-segment variants.

We rejected:
- computing the binding analysis only for the attempt that reaches the Explainer (it restructures `solve()` under #156, and changes `run_optimizer`'s output or its description);
- lowering the binding budget (it changes proven sets broadly);
- trimming the `run_optimizer` output the LLM sees (it could shift live behaviour for little cost gain).

## Consequences

- **Estimated effect on the demo session**, from the table above: D1 saves about 31 s a revision (twice), and D2 and D3 about 36–50 s of the loop-back, on this machine. On a quiet machine the compute left is about 45 s, dominated by the first generation, both binding analyses and the solves. With about 30–45 s of LLM calls, the demo is likely still above 60 s until D5, D6, D7 or D10 land. D9 measures it.
- **No cassette changes.**
  - D1 is bit-identical.
  - D2 and D3 return the values priced in the first set's batch. Those equal a fresh narrowed pricing whenever the narrowed batch has a line at the window's first week in each region, as the demo's does. Otherwise, a cumulative sum starts at a different week and the last bits can differ, far below the paisa the solver rounds to.
  - Tool content is not in the request hash (ADR 0049 D9).
  - The offline replays (`make check-cassettes` and `make eval-smoke`) report no misses.
- **Tests:**
  - line effects of a batch equal each line alone, bit for bit, on fakes and on the fitted small world, and the baseline is forecast once per region;
  - relations lookups survive a caller editing a returned table and a pickle round trip;
  - every narrowing, including one that keeps nothing, equals generating it narrowed, with nothing predicted again, on fakes and on the fitted small world;
  - narrowing is validated as generation validates it;
  - the facts price each pair once;
  - the tool reads a stored set's narrowing off it and shares its facts;
  - session time excludes scoring, and LLM time is the wait on the LLM.
- **The `model`-marker speed tests are unchanged.** They time `solve` without the binding analysis (ADR 0039) and the simulation of a 100-line plan, which were not the gap.
- There is no migration and no new configuration. The API contract gains only the report's `llm_s`.
