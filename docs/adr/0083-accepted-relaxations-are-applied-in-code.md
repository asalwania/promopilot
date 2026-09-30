# Code applies an accepted relaxation to the Context agent's reading, and the LLM never reads it

#165 comes from #160's label check (ADR 0076 D5). In the recorded demo, accepting "lower the clearance target for SKU0006 to 59.86% sell-through" also lowered SKU0002's target to 0.5986. ADR 0070 needs SKU0002 to keep its 60%.

## Why the Context agent misread it

We replayed the demo's four Context readings from the committed cassettes offline:

- In rounds 1–3 the LLM read `clearance: [{"400g namkeen packs", 0.6}]`, so SKU0002 and SKU0006 were both at 60%.
- In round 4 it read `[{"400g namkeen packs", 0.5986}]`, so both SKUs were at 59.86%.

The prompt's wording did not cause this, and even a perfect LLM could not have read it correctly:

- **A clearance ask can only name a phrase.** `BriefResolver.products` resolves a clearance ask's words by category, subcategory, brand and pack size, never by SKU id. The correct reading, `[{"400g namkeen packs", 0.6}, {"SKU0006", 0.5986}]`, only asks 'Which SKUs should be cleared when the brief says "SKU0006"?'. So the misread was the only reading that planned.
- **The first ask wins.** `_clearance_targets` keeps a SKU's first target, so a later, narrower ask would be ignored anyway.
- **The structure never reached Context.** `AmendAnswer` and `PlanningState.amendments` carried only the accept's text. The `Relaxation` itself was stored only with the session's amendment.

We chose these decisions with the owner (D1–D6 on #165; every recommended option except D6, see below).

## Decisions

- **D1. Code applies an accepted relaxation after each reading of the brief, and the LLM never reads its text.**
  - `resume_with_acceptance(graph, thread, relaxation)` resumes Approval with an `AmendAnswer` that carries the `Relaxation` next to its text (`relaxation_amendment`, ADR 0052 D7).
  - The Approval node appends an `AcceptedRelaxation(revision_number, relaxation)` to `PlanningState.accepted`, not the text to `amendments`. So `amendments` holds only the manager's own words.
  - Every Context reading (`read_context(..., accepted=...)`) reads the brief, the answers and the text amendments with the LLM, or with the rules when it is down. `apply_accepted` then applies each accepted relaxation, oldest first, with `optimizer.relaxed_request`.
  - The route is unchanged: Approval → Context → Planner. The round's assumptions are fresh.
  - The API, the cassette recorder and the eval runner all accept through `resume_with_acceptance`. The amendment's text is still stored with its relaxation, shown on the audit trail and named in the `amended` trace event. The recorder still lists it in the manifest.
  - This amends ADR 0052 D7 ("the Context agent reads it like any other amendment"). D7 rejected skipping Context, which makes two routes and leaves assumptions stale; this keeps one route and rewrites the assumptions.
  - We rejected a v2 of the amendments prompt with per-SKU rules plus a SKU-id resolution. It re-hashes every Context request with amendments, and it still depends on the model obeying.
  - We rejected rewording the accept text only. The LLM still has no way to say one SKU.
  - We rejected adding `sku_ids` to `ClearanceAsk`. That schema change re-hashes every Context request of every session and scenario.
- **D2. A change applies while the fresh reading still gives the value it relaxed from.** That value is `RelaxedConstraint.current`, compared per SKU for a clearance target and per region for a cap.
  - The minimum margin, the promoted-SKU cap and the KVI tolerance are compared as `plan_limits` applies them, since that is what the optimiser relaxed.
  - A later amendment that states another value for the field, such as "clear 50% of the namkeen" after the accept, wins.
  - A relaxation accepted after another one relaxes from the first one's value, so both apply in turn.
  - Known limit: a later amendment that restates exactly the value the relaxation relaxed from ("back to 60%") cannot be told apart from no change, so the relaxation still holds.
  - We rejected always applying the relaxation last, which would ignore the manager's newer words. We also rejected storing the request each accept was made on, which is more state with the same limit.
- **D3. The assumptions say so, with no API change.**
  - The marketing budget, a regional cap, the minimum margin, the promoted-SKU cap and the KVI tolerance each have one assumption. Its value is rewritten in place, with source `brief`, confidence 1 and the note "The accepted relaxation of plan revision N."
  - A clearance target is per SKU, and the brief's assumption may cover several SKUs ("60.0% … SKU0002, SKU0006"). So an assumption for the relaxed SKU follows it, such as "59.86% sell-through for SKU0006", noted "The accepted relaxation of plan revision 3: it replaces the 60.00% the brief asks for SKU0006." A dropped target reads "none for SKU0006".
  - We rejected a new `AssumptionSource.RELAXATION`, which changes the API contract and the frontend. We also rejected leaving the reading as it was, which would show 60% while the plan uses 59.86%.
- **D4. `resume_with_acceptance` is a new graph entry point**, beside `resume_with_amendment`. It writes the text itself, so no caller can send a text that differs from its relaxation. We rejected an optional `relaxation` argument on `resume_with_amendment`.
- **D5. Free-text per-SKU clearance changes are #174.** A manager can still type "clear only 50% of SKU0006", and the two gaps above still apply to it. Accepts no longer do. #174 fixes them with no hash change to any recorded reading.
- **D6. The main session re-records the demo on this branch before merge** (`make record-cassettes ONLY=demo`, with the owner's OK). The owner chose this over folding it into the full re-record that #157 and #159 plan.

## What replays and what is recorded again

A Context request depends on the brief, the answers, the text amendments, the prompt and the schema. This change touches none of them, and the accept's text no longer reaches the LLM:

- **The demo's round-4 Context request is now byte-identical to round 3's.** So it replays from round 3's cassette (4605a43c…), and the committed-cassette test reads it that way.
- **Round 4's planning request changes**, since SKU0002 is back at 60%. So what round 4 asks next is new:
  - the planner agent's opening message embeds the request, so its ten steps are new;
  - so are the Critic's feedback call and the Explainer, whose view carries the request changes.
  - These are the demo's cassettes 23–34 in the manifest. The eval scenario `demo-budget-cut-drop-west` replays the app's cassettes, so it misses the same requests until they are recorded.
- **Nothing else changes.** Rounds 1–3 and every other session and scenario keep their hashes.

## Consequences

- **New public names** in `promopilot.agents`: `AcceptedRelaxation`, `apply_accepted` and `resume_with_acceptance`. `PlanningState` gains `accepted`, `AmendAnswer` gains `relaxation`, and `read_context` gains `accepted`.
- **Checkpoints.** A checkpoint from before this change has no `accepted` and reads as empty. A session that accepted a relaxation before it keeps the text in `amendments`, which the LLM still reads there.
- **The rule fallback accepts too.** With the LLM down or no cassette, an accept is applied like any other time. This lifts ADR 0076 D8's limit ("the rules cannot read an accepted relaxation's text: they ask which SKU it means"). The eval runner's test now accepts with the LLM down throughout.
- **ADR 0076 D5 is unchanged.** Extraction still scores the final request against the labels with the accepted values in place. After the accept round is recorded, the demo scenario's `clearance_targets` should match.
- There is no migration, no API or report contract change, no prompt or schema change and no new configuration.
- **This amends:**
  - ADR 0052 D7 (how an accepted relaxation reaches the request);
  - ADR 0070 (the recorder accepts through `resume_with_acceptance`);
  - ADR 0076 D2 and D8 (how the runner accepts, and the rule-fallback limit).
