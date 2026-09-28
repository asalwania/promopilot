# The scenario suite has SPEC §12.1's 32 scenarios at four as-of weeks, briefs the rules can read, a seed-42 coherence test, and its own cassettes that a record mode adds to

E9's #56 grows the eval suite from ADR 0056's three starter scenarios to SPEC §12.1's 32, across the nine groups. It also adds `no_strong_substitutes_together`, which ADR 0062 D6 deferred here.

SPEC §12.1, spec #11 and #56 leave open:

- how many scenarios each group has, and how the count is tested;
- which as-of weeks the scenarios plan at (ADR 0008);
- how the suite gets cassettes, and what `make eval` does with a scenario that has none;
- how briefs are phrased, and what checks that each scenario tests what it says;
- what a "strong" substitute is, and when two are promoted "together";
- how the competitor price war and the mid-plan amendments are set up;
- the file layout, the names and the seeds.

We chose these with the owner (D1–D11 on #56; every recommended option).

## Decisions

- **D1. The suite has exactly SPEC §12.1's counts, 32 scenarios.**
  - Standard festive 6, tight budget 4, overstock clearance 4, competitor price war 4, regional holidays 3, heavy cannibalisation 3, vague or conflicting 3, infeasible constraints 2, mid-plan amendments 3.
  - The three starter scenarios count, so 29 are new.
  - The count test counts by each scenario's `group` field. It asserts at least SPEC's count per group and at least 30 in all, so adding scenarios later does not break it.
- **D2. Scenarios plan at four as-of weeks** (ADR 0008). The seed-42 calendar puts week 0 at 2024-09-30.

  | As-of week | Festivals in reach | Scenarios |
  |---|---|---|
  | 50 | Durga Puja 2025 (week 52), Diwali 2025 (week 55) | 7 |
  | 62 | Christmas 2025 (week 64), Pongal and Lohri 2026 (week 67) | 9 |
  | 82 | off-season: weeks 84–87 hold no festival | 6 |
  | 104 | Durga Puja 2026 (week 107), Diwali 2026 (week 109), Christmas 2026 (week 116) | 10 |

  - The models see four different histories, which is ADR 0008's reason for a movable clock.
  - Each distinct week costs one fit per `make eval`, 35–60 s. Three are new.
  - We rejected putting everything at week 104 and reaching the festivals through the horizon. It needs one fit, but the models would only ever see one history. We also rejected one week per festival, which costs more fits.
- **D3. The eval keeps its own cassettes in `backend/evals/cassettes/`, and a record mode adds to them.**
  - Why a separate folder:
    - `make record-cassettes` plays `cassettes/sessions.json` on Postgres with the registered models, which are trained as of week 104. It cannot record a scenario planned at another week.
    - It removes every cassette its manifest does not list, and `manifest_problems` reports such cassettes as orphans (ADR 0054).
    - Thirty more scripts would add about half an hour to CI's `--check`.
  - **Replay** reads the eval's folder first and then the app's (`promopilot.evals.cassettes.replay_provider`). The starter scenarios therefore keep replaying the committed app cassettes.
  - **Recording** answers from either folder first and asks the live model only what neither holds. It writes that answer into the eval's folder (`recording_provider`). The command is `python -m promopilot.evals --record [--only …]`, run as `make record-eval-cassettes`, which forces `LLM_PROVIDER=openai`. It refuses `replay` and `fake`, and it prints the live calls, tokens and cost.
  - Recording is additive: there is no manifest and nothing is pruned. To record afresh, empty the folder first.
  - A scenario with no cassettes falls back, as ADR 0056 D11 has it. Its run lists what fell back.
  - CI does not depend on any recording. The main session records the suite after merge, with the owner's OK (see Recording).
  - We rejected recording only #57's five smoke scenarios now, and leaving the rest to fall back. We also rejected leaving the record mode to #57 and running the first full run live without keeping it: judges would then see fallback-only numbers with no key.
- **D4. Briefs state their values explicitly.**
  - Every brief outside `vague_or_conflicting` states:
    - its weeks ("for weeks 54-55");
    - its regions, categories and rupee amounts ("₹1.5 lakh", "₹40k");
    - its percentages ("Keep margin above 16%");
    - its clearance products by name ("400g curd packs", "Aura Shampoo 340ml").
  - The festival is still named, for the LLM and the reader.
  - A test reads each of those briefs with the LLM down, after its amendments, as the Context agent's rules would (ADR 0053). It asserts that the reading asks nothing and that the request matches every label.
  - So an unrecorded replay still plans every such scenario, and the labels are what the brief says.
  - Two phrasings the rules could not read were changed:
    - "Snowpeak Frozen Snacks 1kg" names the category Frozen and the subcategory Frozen Snacks. The scenario clears Aura Shampoo 340ml instead.
    - A KVI tolerance above policy's 2% is flagged as a loosening (ADR 0007). The price-war briefs ask for 1–2%.
- **D5. A coherence test checks each scenario on the seed-42 world** (the `default_dataset` fixture, about 3 s):
  - every labelled window starts after the as-of week (also a `Scenario` validator) and ends within the horizon;
  - every named SKU exists;
  - each clearance SKU has available stock in every labelled region at the scenario's week;
  - each price-war scope has at least one undercut KVI at its week (`read_competitor_gaps`, kvi only), since `kvi_response_present` fails when none is undercut;
  - each heavy-cannibalisation scope holds at least two strong substitute pairs;
  - each group expects what it tests:
    - clearance: `meets_clearance` for every target;
    - price war: `kvi_response_present` and a KVI tolerance;
    - regional holidays: `excludes_region` outside the scope;
    - heavy cannibalisation: `no_strong_substitutes_together`;
    - infeasible: a `relaxation_touches` and clearance targets;
    - mid-plan: amendments with `diff_changes` or `excludes_region`;
    - vague or conflicting: a field to ask about or flag.

    Only the infeasible group expects `declares_infeasible: true`.

  It does not solve anything, so a scenario can still be feasible or infeasible only in name. The full run below checked that.
- **D6. `no_strong_substitutes_together: true`** (`promopilot.evals.substitutes`).
  - **Strong:** a pair is strong when it is in the ground truth's `substitute_pairs` and the larger of its two directed true θ is at least `STRONG_SUBSTITUTE_THETA = 0.5`. At θ = 0.5, a 20% cut on one SKU costs the other about 10.6% of its units. That covers about the top 60% of the generator's U[0.3, 0.8] range: 80 of the seed-42 world's 91 true pairs.
  - **In scope:** both SKUs are in the final request's categories, and among its named SKUs when it names any.
  - **Together:** plan lines promote both SKUs in the same region, with at least one common promo week and a common target segment. All customers overlaps every segment, and a BUNDLE promotes its partner, so a bundle of two substitutes counts. These are the conditions under which ADR 0033's pairwise cannibalisation term is not zero.
  - **Failure:** the property fails with no final revision. Following `kvi_response_present`, it also fails when the scope holds no strong pair, since it then tests nothing.
  - The runner reads the pairs from `EvalWorld.ground_truth` (ADR 0064) and the products. `check_property` takes them as `substitutes`.
  - We rejected region and overlapping weeks alone, which would fail segment-exclusive pairs that do not interact. We also rejected "any true pair" (every true θ is at least 0.3) and the world's median θ, which is opaque in the report.
- **D7. The competitor price war changes nothing in the world.** Its scenarios pick categories, regions and weeks where the seed-42 competitor prices already undercut KVIs by the policy's 5% threshold, and D5 guards that. At every week, North has undercut KVIs in Home Care (6), Staples (5), Bakery (3) and Beverages (2). Each brief asks for a KVI tolerance, some with a margin to protect, and expects `kvi_response_present: true`. We rejected a per-scenario competitor price shock: it needs its own world, fit and ground truth.
- **D8. Mid-plan amendments are text only, from the existing `amendments` list.**
  - The demo starter cuts the budget and then drops West.
  - `amend-budget-cut-christmas-2025` cuts the budget (`diff_changes: marketing_budget`).
  - `amend-add-region-extend-offseason` adds East and then extends the window (`diff_changes: promo_window`).
  - Accepting a relaxation (`/amend {"accept_relaxation": true}`) is out of scope, since the runner sends only text.
- **D9. Infeasible and vague scenarios.**
  - Only clearance targets can make a plan infeasible (ADR 0044), so both infeasible scenarios ask for more clearance than the other constraints allow:
    - 95% of the 400g namkeen stock with a ₹10k budget;
    - 90% of the 400g curd stock with margin above 35%.

    Both expect `declares_infeasible: true` and `relaxation_touches: clearance_target`.
  - The vague or conflicting group has:
    - the no-budget starter (`asks_clarification: marketing_budget`);
    - a margin allowed down to 5%, below policy's 15% floor (`flags_assumption: min_margin`);
    - a brief with no category, answered "Beverages" (`asks_clarification: scope.categories`).
- **D10. One flat YAML file per scenario, with kebab-case names that say what it is** (`price-war-staples-christmas-2025`), as ADR 0056 D1 has it. The starters keep their names. Tests read groups from the `group` field, never from a name or a folder.
- **D11. Every scenario plans with seed 0**, as the starters do, so no difference between scenarios comes from the seed.

## Recording

From the repository root in Git Bash, with `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-4.1-mini` in `.env`. It needs no Docker, `make data` or `make train`:

```bash
make record-eval-cassettes                    # every scenario; ONLY="a b" records some
make eval                                     # then replays them with no key
```

Our estimate for all 32:

- about 37 planning rounds: 32 first rounds, 5 more from amendments, and a few Context-only clarify rounds;
- roughly 600–900 live calls;
- $0.06–0.2 a round at gpt-4.1-mini, going by ADR 0054's measurement. That is **about $2–7.5 (₹190–720 at USD_INR_RATE 96)** in all;
- about **1.5–3 hours**, dominated by the optimiser, plus about 4 minutes of fits.

The three starters replay the app's cassettes and cost nothing. Five smoke scenarios alone would cost about $0.3–1 and take 15–30 minutes.

## Consequences

- **New public names** in `promopilot.evals`:
  - `NoStrongSubstitutesTogether`, `SubstitutePair` and `STRONG_SUBSTITUTE_THETA`;
  - `promopilot.evals.substitutes`;
  - `promopilot.evals.cassettes` (`EVAL_CASSETTE_DIR`, `replay_provider`, `recording_provider`, `LiveUsage`).
- `check_property` takes `substitutes`.
- `python -m promopilot.evals` takes `--record` and `--cassettes`. With `LLM_PROVIDER=replay` it now replays the eval's folder before the app's.
- `make record-eval-cassettes` is new.
- A `Scenario` whose labelled window starts at or before its as-of week is refused.
- There is no migration, no API change and no new configuration.
- **Runtime:** a full `make eval` replays 32 sessions of 150–250 s each on an idle machine (ADR 0056), plus four fits. That is **about 80–130 minutes**; `RUNS=5` for consistency is five times that. The first full replay with no eval cassettes is described below.
- Until the suite is recorded, the 29 new scenarios fall back on replay:
  - Context reads by rules, which D4 guarantees still plans them;
  - the planner runs its default sequence;
  - the Explainer uses its template.

  So they have no grounding value and cost nothing, and extraction accuracy measures the rules rather than the LLM.
- #57 picks its five smoke scenarios from this suite, and CI replays them on Linux. A number fitted in memory on Linux could format differently from the Windows recording and miss (ADR 0054 D12). The smoke job would show it.
