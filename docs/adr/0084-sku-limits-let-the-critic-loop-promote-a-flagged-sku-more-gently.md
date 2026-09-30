# SKU limits let the Critic loop promote a flagged SKU more gently: `generate_candidates`' `sku_limits` caps one SKU's depth or mechanisms, only ever tightening, and the Critic's feedback leads with it

#141 comes from the E8 exit review (#10). The e2e and clarify sessions end with open issues the Critic loop could not resolve. #149's recording also showed the demo's accept-relaxation round running the planner to the Critic's cap: 4 attempts, with new risk findings each time.

- Until now the planner's only lever for a finding about one SKU was to leave the SKU out with `exclude_sku_ids` (ADR 0059 D1). That throws away all of the SKU's value.
- ADR 0078's objective tolerance then often keeps the first attempt anyway, because the attempt without the SKU gives up more than 5% of the objective.
- On the small test world, SKU0008 at 20% off takes 76.4% of the plan's promo spend, which is over a 50% line limit. Capping it at 10% off keeps it in the plan under the limit and gives up 10.6% of the plan-time objective. Leaving it out gives up 38.9%.

The issue asks for a per-SKU mechanism or depth lever that only tightens, with loosening refused as a structured error, and with Critic feedback that names the lever. SPEC and the ADRs leave open:
- where the lever lives;
- which regions it covers;
- what "loosening" means when the brief has no per-SKU limits;
- whether a clearance target can be limited;
- which depth it compares;
- how the planner learns the depth to go below;
- the order of the feedback;
- how to measure the issue's "open-issue count".

We chose these with the owner at #141's decision gate (D1–D9, every recommended option).

## Decisions

- **D1. The lever is `generate_candidates`' `sku_limits`, not a `run_optimizer` argument.**
  - Each `SkuLimit` (`promopilot.domain`) is `{sku_id, max_depth_pct?, mechanisms?}` and sets at least one of the two.
  - `generate_options(..., sku_limits=)` in `promopilot.optimizer` drops every option the limits rule out, before it is enumerated.
  - The candidate set id covers the limits, like every other argument. The plan revision and its mechanism comparison (ADR 0041) are built from that set, so neither shows an option the limit forbade.
  - ADR 0077's reuse still holds. A loop-back that caps a SKU reads its set off the set generated first. The tally behind it now counts per BUNDLE partner and depth as well.
  - We rejected a `run_optimizer` argument, which is what the issue wrote, in two forms:
    - filtering inside `solve`: the revision's comparison would show forbidden options, and it conflicts with #159's rewrite of `solver.py`;
    - filtering into a derived candidate set: a second narrowing path beside `generate_candidates`, whose other narrowings the prompts already teach.
  - `solver.py` and `run_optimizer.py` are untouched.
- **D2. A limit covers one SKU in every region, as anchor and as BUNDLE partner.**
  - A BUNDLE discounts both SKUs at its depth, so a capped partner caps the bundle's depth. A partner limited to other mechanisms has no BUNDLE.
  - A price match deeper than the cap is not offered, and is not listed in the summary.
  - We rejected an optional region per limit. It is more precise, because findings name a region, but it is a new shape and `exclude_sku_ids` is per SKU too.
- **D3. A limit may only tighten. Anything else is `invalid_input`**, as a `ValueError` from `generate_options` that the tool hands the LLM as a structured error. The messages are:
  - `loosens company policy: SKU's max_depth_pct N is above the M% maximum discount`;
  - `loosens the call: SKU's mechanisms name X, which the call leaves out`, for a mechanism outside the call's `mechanisms`;
  - `not in the planning request's scope`;
  - `limits a SKU the call does not keep`, for a SKU outside `sku_ids`;
  - `both limited and left out`, for a SKU also in `exclude_sku_ids`;
  - `limits a SKU twice`;
  - `leaves SKU no option: leave it out with exclude_sku_ids instead`, when no grid depth or price match survives.

  `loosening()` in the planner is unchanged: the brief has no per-SKU fields to loosen. We rejected clamping a loose limit silently, and also refusing a limit that happens to allow every option the SKU has.
- **D4. A clearance target of the brief cannot be limited** (`may not limit a clearance target of the brief`).
  - A cap could put its target out of reach. The attempt would then come back INFEASIBLE, and the Critic ends the loop on INFEASIBLE.
  - This matches ADR 0059 D1 for `exclude_sku_ids`. A clearance target's finding keeps its "stays in the plan" feedback.
  - We rejected allowing it with the solver reporting the shortfall, and allowing mechanism limits only.
- **D5. `max_depth_pct` compares a plan line's nominal `depth_pct`**, the depth the plan and the findings show.
  - A BOGO line is 50% deep, so a cap under 50 rules BOGO out.
  - We rejected comparing the effective discount. It is exact for FIXED_PRICE's charm price, but the planner never sees it.
- **D6. A SKU's finding message names its mechanism and depth**, e.g. "SKU0006 in West (PCT_OFF at 30%): …". This applies to line over-concentration, heavy cannibalisation and stock-out risk.
  - Each Critic loop-back opens a fresh planner conversation with the findings alone, so this is how the planner learns what to go below.
  - The depth is in the message, so feedback that cites it stays grounded (`check_numeric_grounding`).
  - ADR 0059 D3's repeated-findings check compares messages, so it still works; a cap that moves the depth changes the message.
  - We rejected putting the depth in the feedback alone, which the grounding check would refuse.
- **D7. The feedback leads with the cap and falls back to leaving the SKU out.**
  - Line over-concentration: "Spread the promo spend: cap SKU's depth below N% with generate_candidates' sku_limits, or else leave SKU out with generate_candidates' exclude_sku_ids, …".
  - Heavy cannibalisation adds "or limit its mechanisms".
  - Stock-out risk keeps narrowing the target segments between the two.
  - Category and region over-concentration are unchanged.
  - The prompts change:
    - Planner v4 lists `sku_limits` among the narrowings. For a finding about one SKU it says to cap the SKU below the depth the finding shows, or limit its mechanisms, and to leave it out only when a cap cannot fix the finding.
    - Critic v3 lists the lever and drops "It cannot choose a mechanism or depth for one SKU".
    - The planner's refusal of a loosened request names `sku_limits`.
  - We rejected keeping exclusion first for heavy cannibalisation. A shallower depth does not always lower the cannibalisation share, but the planner can still fall back, and ADR 0078's tolerance favours the gentler fix.
- **D8. The eval report adds `open_issues`**, the measure the issue's "open-issue count" asks for.
  - Each `RunResult` records the code of each open issue on its final plan (`open_issues`).
  - The metric's value is the median number per final plan, over the runs that ended with one. Its count is the plans with any open issue, and its breakdown is the total and the count per code.
  - It is reported with no target and `direction` `at_most`, in a new `count` unit. `/evals` shows it under Plan quality.
  - `make api-types` regenerates the frontend types and `docs/api.md`.
  - We rejected counting from a one-off replay in the PR alone. The next change to the Critic would have no baseline.
- **D9. #141 is built on #157 (ADR 0078) and re-recorded once.** The main session records the app sessions and the eval suite on this branch with the owner's OK. This agent records nothing.

## Recording

The planner and Critic prompts, `generate_candidates`' schema (sent in every planner request's tool list) and the SKU-level finding messages all change. So every planner request, and every Critic request with findings, misses the committed cassettes. The Explainer's requests change with the plans. The Context agent's requests are unchanged: `PlanningRequest` is untouched.

```bash
make record-cassettes        # the four app sessions (e2e, demo, clarify, regional)
make check-cassettes
make record-eval-cassettes   # the 32-scenario suite, after emptying backend/evals/cassettes/
make eval-smoke
```

Until then, these are expected red:
- the images job's `python -m promopilot.cassettes --check`, where the planner's requests miss;
- the smoke eval in CI, on cassette misses;
- the Playwright assertion that the Explainer's LLM answer explains the plan, because the planner degrades on the miss.

After re-recording, drop the demo's accept round (`("demo", 3)`) from `ROUNDS_AT_CAP` in `test_committed_cassettes.py`, if it no longer runs to the cap. A live model is not bound to converge, so the exemption stays if it still does. Then compare the eval report's `open_issues` before and after on the scenario suite.

## Consequences

- **New public names:**
  - `SkuLimit` in `promopilot.domain`;
  - `GenerateCandidatesInput.sku_limits`;
  - `generate_options(..., sku_limits=)`;
  - `open_issues` in `promopilot.evals.metrics`;
  - `RunResult.open_issues`;
  - the `count` unit of `Metric`.
- The eval report's JSON and its API schema gain `open_issues`. There is no migration and no new configuration.
- The prompts are now planner v4 and critic v3.
- **What this amends:**
  - ADR 0059: D1, since exclusion is no longer the only lever for one SKU; and D5, the template feedback and the prompts;
  - ADR 0051 D1: the template feedback's levers;
  - ADR 0049: the levers the planner may use, where a SKU limit only tightens.
