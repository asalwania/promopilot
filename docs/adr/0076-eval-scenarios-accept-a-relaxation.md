# An eval scenario's amendment can accept the waiting revision's relaxation, sent as the API sends it; the labels stay as stated and the accepted values replace them when scored

#160 comes from #58's target review of the first full eval run. The eval runner could only send text amendments (ADR 0065 D8), so `demo-budget-cut-drop-west` ended at revision 3. That revision is `INFEASIBLE`: SKU0006 reaches 59.87% of its 60% target. So the scenario failed `meets_clearance: SKU0006`. #149 (ADR 0070) taught the app's recorder an `accept_relaxation` step, and the recorded demo now accepts its relaxation and approves revision 4.

The ticket, SPEC and ADRs 0056, 0065 and 0070 leave open:

- the scenario file's shape for the step;
- what happens when there is no relaxation to accept;
- whether the eval approves;
- what the demo scenario expects after the accept;
- how the labels are scored once a relaxation's values are in the request;
- how an accept counts in the report;
- whether the demo needs a new recording.

We chose these with the owner (D1–D8 on #160; every recommended option).

## Decisions

- **D1. An amendment is a text or `{accept_relaxation: true}`.**
  - `Scenario.amendments` is `tuple[str | AcceptRelaxation, ...]`. `AcceptRelaxation` holds only `accept_relaxation: Literal[True]`, so `false` and unknown keys are refused when the file loads.
  - This mirrors the step in `cassettes/sessions.json` and the body of `/amend` (ADR 0052 D7, ADR 0070 D1). A text amendment is still a plain string, so the other 31 files are unchanged.
  - `Scenario.stated_amendments` lists the texts only.
  - We rejected a scenario-level `accept_relaxation: true` flag, which leaves its place in the order implied. We also rejected ordered `steps` like `sessions.json`, which ADR 0056 D1 already rejected and which would change every file.
- **D2. The runner sends the relaxation exactly as the API does, and refuses a revision with none.**
  - When the session waits for approval, an accept step takes `acceptable_relaxation(revision)`. It sends `relaxation_amendment(relaxation)` through `resume_with_amendment`, as `SessionService.amend` and the recorder do (ADR 0070 D2).
  - A revision with no relaxation to accept fails the run: `RunOutcome.FAILED` with "amendment N accepts a relaxation, but plan revision M has no relaxation to accept". The API answers 409 in this case and the recorder fails.
  - The refusal cannot happen when the file loads, because whether a revision has a relaxation depends on the plan, and so on the LLM.
  - We rejected skipping the step, which hides the problem. We also rejected a new `refused` outcome, which would change the report schema and the dashboard.
- **D3. The runner still never approves** (ADR 0056 D3).
  - `declares_infeasible: false` states the approval rule, since `approval_refusal` refuses exactly an `INFEASIBLE` revision (ADR 0046 D10).
  - We rejected an `approve` step: it adds nothing the report scores, and it needs a new outcome.
- **D4. The demo scenario plans, amends with "Budget cut to ₹6 lakh" and "Drop West", then accepts.** It expects:
  - `declares_infeasible: false`;
  - `excludes_region: West`;
  - `meets_clearance` for SKU0002 and SKU0006;
  - `diff_changes: clearance_targets`. Revision 4's diff is from revision 3, where only the clearance target changes, as ADR 0070 D6 checks through the API.

  `meets_clearance` checks the targets the final request holds. After an accept, that is the relaxed one (59.86% for SKU0006 when this was written).
- **D5. The labels stay what the scenario states; each accepted relaxation replaces the labelled values it changes before extraction is scored.**
  - `match_fields(labels, request, accepted=...)` applies each change in turn:
    - the marketing budget, the minimum margin and the KVI tolerance take the relaxed value, and a tolerance turned off is expected off;
    - a regional cap takes the relaxed value for its region;
    - the promoted-SKU cap takes the relaxed count;
    - a clearance target takes the relaxed sell-through, or is dropped.
  - A change never labels a field the scenario leaves out.
  - So extraction still scores the Context agent's reading of the accept text, and the labels do not break when the optimiser's relaxation moves. #156 and #158 are changing the optimiser now.
  - The readable-by-rules suite test reads `stated_amendments` only. An accept's text only exists once there is a plan.
  - We rejected scoring the request from before the accept, which leaves a misread accept unscored. We also rejected writing the relaxed value (0.5986) into the YAML, which breaks as soon as the optimiser's relaxation moves.
- **D6. An accept counts in `amendments_applied`**, since accepting is an amendment (ADR 0052). There is no report schema change and no `make api-types`. Revision 4's Explainer run counts toward grounding like any other.
- **D7. The demo scenario should replay the app's committed cassettes, with no eval recording.**
  - #149 recorded the demo's accept round into `backend/cassettes/`. The app's manifest lists the accept text "Accept the smallest relaxation: lower the clearance target for SKU0006 to 59.86% sell-through."
  - Rounds 1–3 already replay whole on the eval's world (ADR 0056, ADR 0065). So revision 3 carries the same relaxation, the runner writes the same text, and the accept round asks the same requests. The layered replay reads the eval's folder and then the app's.
  - It was checked offline (replay, no key) with `make eval ONLY=demo-budget-cut-drop-west`. The result is in the pull request.
  - If #156 or #158 change the demo's plans, the app's and the eval's cassettes are both re-recorded then, whatever this change does. Record mode reads the app's folder first, so the demo costs nothing there when the app's cassettes are current.
- **D8. Tests.**
  - **Scenario tests:** the step parses, and `false` or unknown keys are refused. The demo carries the step and its expectations.
  - **Label matching:** `match_fields` applies each kind of change.
  - **Runner, on the small world:** an unreachable clearance target is accepted and re-planned into revision 2, which is not infeasible, meets its relaxed target and has a clearance-target diff. Its extraction is scored against the relaxed value. A scenario that accepts when there is no relaxation fails the run with the refusal.
  - The Context agent's rules cannot read an accepted relaxation's text: they ask which SKU it means. So the runner test's scripted LLM reads only that amendment, and everything else falls back.

## Consequences

- **New public names** in `promopilot.evals`: `AcceptRelaxation`, `Amendment` and `Scenario.stated_amendments`.
- `match_fields` takes `accepted`.
- **This amends:**
  - ADR 0065 D8 (amendments are no longer text only);
  - ADR 0056 D2 (an accept step can fail a run).
- There is no migration, no API or report contract change and no new configuration.
- The demo scenario is not a smoke scenario, so CI's smoke eval is unchanged.
