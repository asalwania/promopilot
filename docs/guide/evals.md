# Evals

The scenarios, the metrics, the report and the CI smoke eval. How to run them is in the [README](../../README.md#evals); the claim and the numbers are in [nine-blocker.md](../nine-blocker.md).

## Evals

`make eval` measures the reliability claim (SPEC §12, ADR 0056). It plays every scenario in [`backend/evals/scenarios/`](../../backend/evals/scenarios) as a planning session through the full agent graph, in process, and scores each session's final plan revision. `ONLY="a b"` runs the named scenarios, `RUNS=n` runs each n times, and `SEED=n` picks the world.

A scenario is one YAML file, named after it:

```yaml
name: demo-budget-cut-drop-west
group: mid_plan_amendments     # one of the nine SPEC §12.1 groups
brief: >-
  Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. …
as_of_week: 104                # the week it treats as today (ADR 0008)
seed: 0                        # its sessions' optimiser and simulation seed
clarifications:                # answers by question id, given only if that question is asked
  marketing_budget: "₹2 lakh"
amendments:                    # made in order, each once a plan waits for approval
  - "Budget cut to ₹6 lakh"
  - "Drop West"
  - accept_relaxation: true    # accept the waiting revision's relaxation, as the API does
labels:                        # the planning-request fields it states, for extraction accuracy
  regions: [North]
  marketing_budget: 600000
expect:                        # properties of the outcome, never an exact plan
  - asks_clarification: marketing_budget
  - declares_infeasible: false
  - excludes_region: West       # the final revision, after every amendment
  - meets_clearance: SKU0002
  - relaxation_touches: clearance_target   # a ConstraintKind the relaxation changes
  - flags_assumption: min_margin           # the final reading flags this field
  - diff_changes: scope.regions            # the final revision's diff changes this field
  - kvi_response_present: true             # the undercut-KVI response is in notes and summary
  - no_strong_substitutes_together: true   # no two strong true substitutes promoted together
```

A `vague_or_conflicting` scenario must name at least one field with `asks_clarification` or `flags_assumption` (ADR 0062).

An amendment is a text, or `accept_relaxation: true`. An accept step accepts the waiting revision's relaxation exactly as `POST /amend {accept_relaxation: true}` does (code applies its values, ADR 0083), and counts in the run's amendments. A revision with no relaxation to accept fails the run, as the API answers 409 (ADR 0076). The labels stay what the scenario states: an accepted relaxation's values replace the labelled values it changes before extraction is scored, and `meets_clearance` checks the target the final request holds, the relaxed one after an accept. The runner never approves; `declares_infeasible: false` says the final revision could be approved. The demo scenario amends twice and expects a feasible revision 3 that meets both 60% targets, with a diff that changes `scope.regions`. `infeasible-tiny-budget-accept` accepts the tiny-budget brief's relaxation and expects a feasible revision 2 whose diff changes `clearance_targets` (ADR 0086).

A labelled promo window must start after the as-of week. `no_strong_substitutes_together` fails when the final plan promotes two strong substitutes in scope together, or when the scope has none to test. Two SKUs are strong substitutes when the ground truth makes them a substitute pair and the larger of their true cross-price effects θ is at least 0.5. They are promoted together when they share a region, a promo week and a target segment, and a BUNDLE's partner counts (ADR 0065).

The suite has SPEC §12.1's 32 scenarios, plus a fourth mid-plan amendment that accepts a relaxation (ADR 0086), one flat file each (ADR 0065):

| Group | Count | As-of weeks |
|---|---|---|
| Standard festive plans | 6 | 50, 62, 104 |
| Tight budget | 4 | 50, 62, 82, 104 |
| Overstock clearance | 4 | 50, 62, 82, 104 |
| Competitor price war | 4 | 50, 62, 82, 104 |
| Regional holidays | 3 | 50 (Durga Puja), 62 (Pongal, Lohri) |
| Heavy cannibalisation | 3 | 62, 82, 104 |
| Vague or conflicting briefs | 3 | 62, 82, 104 |
| Infeasible constraints | 2 | 50, 104 |
| Mid-plan amendments | 4 | 62, 82, 104 |

Week 50 reaches Durga Puja and Diwali 2025, week 62 Christmas 2025 and Pongal/Lohri 2026, week 82 an off-season window, and week 104 Durga Puja, Diwali and Christmas 2026. Every brief outside the vague group states its weeks, regions, categories, rupees and percentages. A test checks that the Context agent's rules read each of those briefs to its labels with the LLM down. Another checks each scenario on the seed-42 world: its SKUs have stock to clear, a price war's KVIs are undercut, and a cannibalisation scope holds strong substitute pairs.

The eval builds its own world: the seed-42 dataset `make data` writes, with its hidden ground truth, and demand and relations models fitted in memory as of each scenario's week (35–60 s per week), so no sales after that week reach them. It needs no Docker, `make data` or `make train`. The LLM is whatever `LLM_PROVIDER` names; with the default `replay`, requests with no cassette fall back as the stack does: the Context agent reads by rules, the planner runs the default sequence and the Explainer uses its template, and each run lists what fell back. The three starter scenarios are the recorded sessions' briefs (`e2e`, `clarify`, `demo`), and on the seed-42 world they replay the committed cassettes whole, taking the recorded routes with nothing falling back. Replay reads the eval's own cassettes in `backend/evals/cassettes/` first, then the app's `backend/cassettes/`. A scenario with no cassettes falls back until it is recorded. Until the suite is recorded, a full run takes about 40 minutes, because the new scenarios plan by the default sequence. Once recorded, it takes about 80–130 minutes (150–250 s a session, plus four fits of 35–60 s, plus about 30 s for each distinct final request to build the baseline and best plans). `RUNS=5` takes five times that. A question the scenario does not answer ends its run with no plan, and a failed session is reported without stopping the others.

`make record-eval-cassettes` records the suite with a live key (`OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4.1-mini` in `.env`; no Docker). It asks the live model only what neither cassette folder holds, writes the answers into `backend/evals/cassettes/`, and prints the live cost. It is additive: to record afresh, empty the folder first. `make record-cassettes` cannot record eval scenarios, since it plays on the week-104 registered models and prunes what its manifest does not list. Recording all 33 is about 37 planning rounds, roughly $2–7.5 (₹190–720) at gpt-4.1-mini, and 1.5–3 hours.

The report goes to `backend/evals/reports/` (gitignored) as `<UTC timestamp>.json` and `.md`, plus `latest.json` and `latest.md`. It shows each metric against its SPEC §12.2 target, one row per run and every failure:

- **Constraint satisfaction** (target 100%): the share of final plans that keep every hard constraint on their own plan-time numbers, checked by `validate_plan` independently of the optimiser (ADR 0012). Infeasible revisions and runs without a plan are counted but not scored.
- **Oracle breach rate** (at most 15%, ADR 0080): the share of the same plans whose true outcome, scored by the oracle on the hidden demand, spends over the budget, misses the minimum margin or sells more than the stock, with a count of each.
- **Open issues** (reported, aiming at none): the median number of open issues the Critic left on a final plan, over the runs that ended with one, how many plans have any, and the total by code (ADR 0084).
- **Extraction accuracy** (target ≥ 95%): correct labelled fields over labelled fields, on the final planning request. Sets match as sets, money within ₹1, fractions within 0.01 points, windows and the SKU cap exactly; a run with no request gets every labelled field wrong. A mismatch is listed but does not fail its run (ADR 0062).
- **Clarification behaviour** (target 100%): the share of `vague_or_conflicting` runs that asked about, or flagged, a field the scenario names. Runs of other scenarios that asked a question they do not expect are counted as unneeded asks, with no target.
- **Infeasibility handling** (target 100%): the share of `infeasible_constraints` runs whose final revision is `INFEASIBLE`, proposes a relaxation and names a binding constraint. A solver timeout is not a declaration.
- **Grounding** (target ≥ 98%): the share of Explainer runs the LLM answered (one per revision that waited for approval, amendments included) whose explanation passed numeric grounding. A template for an ungrounded or invalid answer fails; one because the LLM was unavailable, a cassette miss included, is counted but not scored.
- **P50 session time and cost** (reported): the median wall-clock time of the sessions that did not fail, from the brief to the session's end (without fitting the models or scoring the plan), with the median time spent waiting on the LLM (`llm_p50_s`, near 0 under replay) in its breakdown, and their median LLM cost in rupees, the sum of each session's token-usage events priced with `LLM_PRICES`. Replay reports the recorded usage again, so a cassette miss costs nothing. SPEC §6 aims for under 60 s with a live LLM and under ₹20 a session.
- **Model recovery** (ADR 0064), once per report on the models fitted as of the world's default week (104, the models `make train` registers; fitted if no scenario uses that week):
  - **Elasticity recovery** (target ≤ 20%): the median absolute % error of the estimated own-price elasticity against the true one, over every SKU × segment, with how many are within 20%.
  - **Substitute and complement precision / recall** (targets ≥ 0.8 / ≥ 0.7): the pairs the relations model keeps, as unordered pairs across the catalogue, against every true pair.
  - **Baseline WAPE** (reported, aim ≤ 25%): the demand model's own 12-week holdout WAPE at the store × SKU × segment, store × SKU and region × SKU grains (ADR 0023).
- **Plan quality** (target 90%): the share of scenarios whose every scored plan earns more, by the oracle's objective (incremental profit plus clearance value), than the **rule-based baseline**. That baseline is 20% off the top 10 sellers in scope (units over the 12 weeks before the as-of week), to All customers, in every region of the scope, over the promo window (at most its first 4 weeks), with sellers dropped from the bottom until its expected promo cost fits the budget and any regional cap (ADR 0063).
- **Regret** (target: median 10% or less): (best − ours) / best, where the **best plan** is our own option generation and optimiser run on true-parameter predictions from the ground truth, with the session's work budgets and the scenario's seed, scored by the oracle. It is signed; when the best plan earns nothing, matching it is 0 and earning less is 100%. Each run's regret splits by cause (ADR 0078), against the **default plan**, the same optimiser on the scenario's fitted models for the same request: **model error** (best − default) / best, the **planner**'s choices (default − ours) / best, and **timeouts**, either part whose two plans include one the solver stopped as FEASIBLE. The three sum to the regret. A run whose best plan timed out is flagged and left out of the median whatever its sign (`best_timed_out`); the metric also counts, for each run above the target, its largest part.
- **Consistency** (target 0.9): the mean Jaccard overlap of the SKUs every two runs of a scenario promote. It needs `RUNS` of at least 2 (`make eval RUNS=5`), so the default run shows it as n/a. With the replay provider a scenario's runs are identical: only a live LLM varies them.
- **Expected properties**: each scenario's `expect` list, pass or fail per run.

A second table, **Agent behaviour**, shows per run the fields read right, the questions asked, the flagged assumptions, each Explainer run's source, the session time with its LLM time, and its cost.

The harness builds the baseline and the best plan from each run's final planning request, never from the scenario file, once per scenario seed and request. The report's plan-quality table shows each scored plan against both.

Each run also lists its `cassette_misses`: the hash of every request replay held no cassette for, in any round (ADR 0069), and whether it `passed`: it ran, kept its hard constraints and had every expected property (ADR 0072). `/evals` shows the report.

### Smoke eval in CI

Five scenarios carry `smoke: true`, and CI's `eval-smoke` job replays them on every PR with no key (ADR 0069): `diwali-snacks-beverages` (week 104, standard festive), `diwali-no-budget` (104, vague: asks for the budget), `infeasible-clearance-high-margin` (50, infeasible), `amend-budget-cut-christmas-2025` (62, mid-plan amendment) and `price-war-bakery-beverages-offseason` (82, price war). They cover five of the nine groups and every as-of week, so every model history is fitted on Linux.

`make eval-smoke` runs the same thing locally: `python -m promopilot.evals --smoke --check` with `LLM_PROVIDER=replay`. `--smoke` plays only the tagged scenarios (`make eval SMOKE=1` without the check). `--check` exits 3 when a run:

- ends with no plan (failed, or still asking);
- has a final plan that breaks a hard constraint, or an expected property that does not hold;
- is a vague scenario that neither asked nor flagged, or an infeasible one not declared infeasible with a relaxation and a binding constraint;
- asked anything no cassette holds, named by its request hash.

The ratio metrics (plan quality, regret, extraction, grounding, model recovery) are in the report but never fail the check. A fallback the recording itself made replays as recorded and is not a problem. `--check` needs the replay provider. The job needs no Docker, `make data` or `make train`, takes about 22–28 minutes (four fits and six planning rounds), puts `latest.md` in the job summary and uploads `backend/evals/reports/` as the `eval-smoke-report` artifact. A cassette miss that only CI sees usually means a number formatted differently on Linux (ADR 0054 D12): take the raw number out of the request rather than recording on Linux.
