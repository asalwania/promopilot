# Agent-behaviour metrics score each session's final request, questions, flags, infeasibility and Explainer runs, and its time and cost from its trace

E9's #55 adds the SPEC §12.2 metrics that show the agent behaves: extraction accuracy, clarification behaviour, infeasibility handling, grounding, and P50 session latency and cost. It also grows the expected-property vocabulary of ADR 0056.

SPEC §12.2, spec #11 and #55 leave open:

- how labelled fields are matched, and what the accuracy is a share of;
- what "asks or flags" means, and whether asking when it is not needed counts;
- what "declared infeasible with relaxation" requires;
- which explanations grounding counts, and what a fallback counts as;
- what session time and cost are, and how replay affects them;
- the new properties' definitions;
- the report's layout.

We chose these with the owner (D1–D8 on #55; every recommended option).

## Decisions

- **D1. Extraction accuracy is a micro average by field.**
  - It is the number of correct labelled fields over the number of labelled fields, across every run. It is scored on the final planning request, after the answers and amendments. The breakdown counts the misses per field.
  - A run that ends with no request (it failed, or stopped at a question before any reading) gets every labelled field wrong.
  - A mismatch is listed under the report's failures. It does not fail its run: a run's pass stays its constraints and expected properties (ADR 0056).
  - We rejected the share of runs with every field right, which hides how close they are, and leaving runs with no request out, which hides a failure to read.
- **D2. Field matching rules** (`promopilot.evals.behaviour.match_fields`):
  - `regions`, `categories` and `sku_ids` are sets: order and repeats are ignored. The categories are the resolver's names, so they match exactly.
  - `promo_window` matches exactly, start and end week.
  - `marketing_budget` matches within ₹1. `regional_budget_caps` match when they cover the same regions, each within ₹1.
  - `min_margin` and `kvi_price_tolerance` match within 0.0001 (a hundredth of a point). A request without one does not match a label.
  - `clearance_targets` match when they name the same SKUs, each sell-through within 0.0001.
  - `max_promoted_skus_per_category_per_region` matches exactly.
  - Only labelled fields are scored. A label cannot yet say that a field must be absent.
  - We rejected relative money tolerances, a week's slack on windows and partial credit for sets: the brief states these values, so they should be read exactly.
- **D3. Clarification behaviour.**
  - Only `vague_or_conflicting` runs are scored. A run passes when it asked about a field the scenario names, or its final reading flags that field's assumption.
  - A scenario names fields with `asks_clarification` and the new `flags_assumption`. A question about one item of a field (`clearance_targets.0`) is about the field. Loading refuses a vague or conflicting scenario that names none.
  - The breakdown counts runs that asked, runs that only flagged, and runs that did neither. It also counts **unneeded asks**: runs of the other groups that asked a question their scenario's `asks_clarification` does not expect. That count has no target.
  - We rejected passing on any question or any flag: "Target families" is always flagged. We also rejected counting only questions, since SPEC says "ask or flag".
- **D4. Infeasibility handling.**
  - Only `infeasible_constraints` runs are scored. A run passes when its final revision:
    - is `INFEASIBLE`;
    - has a relaxation with at least one change;
    - names at least one binding constraint (AG-06).
  - A solver timeout, `FEASIBLE` with an unproven relaxation (ADR 0044), is not a declaration and fails.
  - The breakdown counts each missing part, and the runs with no plan.
- **D5. Grounding counts every Explainer run.**
  - The runner records the explanation each plan revision waited for approval with, so the revisions before an amendment count too.
  - An `llm` explanation passed `check_numeric_grounding`, after one regeneration at most (ADR 0050).
  - A template for an `ungrounded` or `invalid_answer` answer failed.
  - A template because the LLM was unavailable, a cassette miss included, checked nothing. It is counted in the breakdown but not scored. So a replayed run with no cassettes has no grounding value, which is honest.
  - We rejected re-checking the final explanation: a template always passes, which inflates the rate. We also rejected failing every template, which blames the Explainer for an outage.
- **D6. The new expected properties:**
  - `relaxation_touches: <ConstraintKind>`: the final revision's relaxation changes a constraint of that kind.
  - `flags_assumption: <field>`: the final reading flags that field's assumption (ADR 0048), such as a minimum margin below the policy floor.
  - `diff_changes: <request field>`: the final revision's diff lists a change to that field (ADR 0052), such as `scope.regions`. This is "correct re-plan and diff" for mid-plan amendments.
  - `kvi_response_present: true`: the planner's response to the undercut KVIs in scope must be in the planner's notes and in the plan summary. The eval recomputes it for the final plan, with `competitors.read_competitor_gaps` on the eval's world at the scenario's week and `CompetitorGaps.undercut_response`, as the planner does (F-08 AC2, ADR 0049). It fails when no KVI in scope is undercut, since the scenario then tests nothing.
  - "Excludes region R after amendment" is ADR 0056's `excludes_region`, which already checks the final revision, after every amendment.
  - **`no_strong_substitutes_together` is deferred to #56.** ADR 0056 D9 gave it to #55, but #55 does not list it. It needs a ground-truth threshold for "strong", which the heavy-cannibalisation scenarios #56 writes will settle.
  - We rejected a string match on "Competitor is … cheaper", which breaks when the wording changes.
- **D7. Latency and cost are reported.**
  - Each run records `session_s`: wall-clock time from sending the brief to its end, without fitting the models. The first run of each as-of week would otherwise carry 35–60 s of fitting. `duration_s` still includes it.
  - Each run records `usage`: the sum of the session's `token_usage` trace events, as the read model sums them (ADR 0047). The runner keeps each session's trace in a `MemoryTrace`, and prices it with `LLM_PRICES` and `USD_INR_RATE`, as the API does.
  - The report has **P50 session time** (seconds) and **P50 session cost** (rupees) over the runs that did not fail. There is no target, as SPEC §12.2 says "report". SPEC §6's budgets (under 60 s with a live LLM, under ₹20 a session) are quoted in the README, not scored.
  - Replay reports the recorded usage again (ADR 0054), so a cassette hit costs what it cost when it was recorded, and a miss costs nothing. A replayed run's latency measures the stack without network time.
  - `Metric` gains `unit` (`share`, `seconds` or `rupees`), so one metric table serves the report and the `/evals` dashboard. `EvalReport.comparable()` also leaves out `session_s` and the latency metric's value and breakdown. Cost stays: it is deterministic under replay.
  - We rejected a separate block for latency and cost, and scoring them against SPEC §6's budgets.
- **D8. Targets and layout.**
  - The targets are SPEC §12.2's: extraction ≥ 95%, clarification 100%, infeasibility 100%, grounding ≥ 98%. A metric with nothing scored passes neither way (`passed` is null).
  - The Markdown gains the six metric rows, in their units, and an **Agent behaviour** table with one row per run: the fields read right, the questions asked, the flagged assumptions, each Explainer run's source, the session time and its cost.
  - The failures list extraction mismatches, clarification misses and what an infeasible run left out.

## Consequences

- **New public names:**
  - `promopilot.evals`: `RelaxationTouches`, `FlagsAssumption`, `DiffChanges` and `KviResponsePresent`;
  - `promopilot.evals.behaviour`: the checks and metrics;
  - `promopilot.evals.report`: `FieldMatch`, `ClarificationCheck`, `InfeasibilityCheck`, `ExplainerRun`, `format_value` and `Metric.unit`.
  - `RunResult` gains `extraction`, `flagged`, `clarification`, `unneeded_asks`, `infeasibility`, `explanations`, `session_s` and `usage`.
  - `Scenario` gains `clarified_fields`.
- `evals.run` takes `pricing`. `check_property` takes the flagged fields, the planner's notes, the summary and the recomputed KVI response.
- There is no migration, no API change and no new configuration. #57 serves the report and generates the frontend types from it.
- Until #57 records cassettes for the eval scenarios, a replayed new scenario has no grounding value and costs nothing, and its run lists what fell back.
