# The Critic loop converges: the planner leaves a flagged SKU out with `exclude_sku_ids`, analyses may narrow the scope, and repeated findings end the loop early

E8 (#135) fixes what the first full-graph recording (#51, ADR 0054) showed about the Critic loop (AG-04, ADR 0051):

- The e2e and clarify sessions always ran all 4 planner attempts. Every attempt came back with the same 3 HEAVY_CANNIBALISATION findings (SKU0006 in West, SKU0035 in North and West), and the plan came out the same. That cost about 3 times the planner calls and optimiser time. Because the recorder answers a repeated request from its first answer (ADR 0054 D12), attempts 3 and 4 were exact repeats of attempt 2.
- The Critic's template feedback said "leave SKU0006 out of generate_candidates' sku_ids". But `sku_ids` is an allow-list, and nothing let the planner leave a SKU out. The model did the opposite and called `generate_candidates` with only the problem SKUs.
- The template's first suggestion, "try another mechanism or a shallower depth for it (compare_mechanisms)", was something the planner cannot do. It has no mechanism or depth of its own for one SKU, and `compare_mechanisms` only analyses.
- The planner often narrowed `request.scope` to reach one SKU, for example `compare_mechanisms` with `scope.sku_ids=['SKU0006']`. `loosening()` refused every scope change, so each such call cost the planner a step: 24 `planner_call_refused` decisions across the e2e and clarify recordings.

We chose these with the owner (D1–D7 on #135; every recommended option).

## Decisions

- **D1. `generate_candidates` takes `exclude_sku_ids`**, the planner's lever for a SKU the Critic flags.
  - These SKUs of the request's scope are left out, in every region. The undercut KVIs among them lose their price-match option.
  - `generate_options(..., exclude_sku_ids=)` in `promopilot.optimizer` does it. The tool answers `invalid_input` for:
    - a SKU outside the request's scope;
    - a SKU also in `sku_ids` ("both kept and left out");
    - leaving out every SKU;
    - a clearance target of the brief, which would make the plan infeasible.
  - It only removes options, so the LLM can only tighten the plan with it, and `loosening()` does not look at it. The candidate set id covers it, like every other argument.
  - We rejected per-(SKU, region) pairs. They are more precise (SKU0006 is flagged only in West) but add a new argument shape, and the issue named a SKU list. We also rejected letting a clearance target be left out and the solver report the plan infeasible, which wastes an attempt.
- **D2. An analysis may narrow the scope; planning may not.**
  - `loosening(given, proposed, *, scope_may_narrow=False)` lets a proposed scope covering only the given regions, categories and SKUs through when `scope_may_narrow` is set. A wider scope is "widens scope".
  - The planner sets it for `compare_mechanisms` only (`ANALYSES`). A test proves its comparison is the same for the full scope and for a scope narrowed to its SKU and region: cannibalisation and halo reach the whole catalogue, and the tool already narrows to one region. A narrowing that leaves out a clearance target's SKU gets the tool's existing `invalid_input`.
  - `generate_candidates` keeps the brief's scope, because the optimiser and `validate_plan` plan against it. Its refusal now names `exclude_sku_ids` and `sku_ids` as the ways to plan fewer SKUs.
  - We rejected keeping the refusal and only rewording the prompt: the model had already ignored "pass the planning request as given" 24 times. We also rejected taking `request` out of `compare_mechanisms`' LLM schema and filling it in from the planner. That is robust, but it makes the planner special-case one tool and show a schema that differs from the tool's input.
- **D3. Findings "repeat exactly" when they are the same multiset of what each says:** kind, code, SKU, region, category and message. The message states the numbers as formatted.
  - The Critic's LLM wording of the feedback is left out, because a live model rewords identical requests (ADR 0054 D12). The raw `actual` and `limit` floats are left out too, as the planner never sees them.
  - When these match, the next attempt would open with the same findings, so it would plan the same again.
  - We rejected comparing only kind, code, SKU, region and category. That stops even when the numbers moved, which can cut off real progress. We also rejected including the wording, which a live run would rarely repeat.
- **D4. `findings_repeated` is a fifth handoff, alongside the cap. This amends ADR 0051 D4.**
  - `critic.handoff` checks it after `plan_valid`, `infeasible` and `default_sequence`, and before `cap_reached`. It compares the latest attempt with the previous one in the same planning round; an amendment starts a new round (ADR 0052).
  - The best attempt goes on as before (ADR 0051 D7), with its findings as open issues.
  - The Critic's `decision` trace event is `findings_repeated`. Its summary says which attempts repeated and which one goes on.
  - `MAX_ATTEMPTS` stays 4 (SPEC AG-04). We rejected also detecting cycles against earlier attempts; the cap bounds those.
- **D5. The feedback stays LLM-worded (ADR 0051 D1), and the templates lead with the lever the planner has.**
  - Every finding about one SKU (line over-concentration, heavy cannibalisation, stock-out risk) names "leave SKU out with generate_candidates' exclude_sku_ids".
  - Stock-out risk also offers narrowing the target segments. Category over-concentration offers a lower promoted-SKU cap, or leaving some of the category's SKUs out. Region over-concentration keeps its regional budget cap.
  - A clearance target of the brief is never sent out of the plan, because `exclude_sku_ids` refuses it. Its feedback says it stays in the plan and the finding stays open; for stock-out risk it offers narrowing the target segments. Such a finding repeats, so the loop stops early (D4).
  - The mechanism-and-depth hint is gone.
  - The prompts change. Critic v2 lists the levers the planner actually has. Planner v3 says to drop a SKU with `exclude_sku_ids` (never by listing the others in `sku_ids`) and that the planner cannot choose one SKU's mechanism or depth. It also says `compare_mechanisms` compares the SKU and region it names, may take a narrowed scope, and does not change the plan.
  - We rejected template-only feedback, which drops the Critic's LLM call. It is cheaper and fully deterministic, but it departs from SPEC §9.6 and ADR 0051 D1.
- **D6. Cost: the worst case stands, and the typical case falls.**
  - ADR 0051 D9's worst case (4 different attempts: about ₹16 on `gpt-4.1-mini`, about ₹88 if the `claude-sonnet-5` fallback answers every step) is unchanged.
  - A round whose findings repeat now stops after 2 attempts. In the #51 recording, e2e's planner input was about 15k tokens for attempt 1 and about 80k for each later attempt. So a live session drops from about 255k to about 95k planner input tokens. Narrowed `compare_mechanisms` calls no longer cost a refused step.
  - The re-recording's cost is printed by `make record-cassettes`. E9 measures cost per session.
- **D7. The committed-cassette test checks convergence offline.** `test_every_recorded_planning_round_converges_or_stops_early` reads `manifest.json` and asserts that no planning round of any recorded session runs the planner `MAX_ATTEMPTS` times. It needs no model and replays nothing. We rejected recording each round's handoff reason in the manifest (a schema change), and leaving convergence to the PR description.

## Recording

This PR changes the planner and Critic prompts, `generate_candidates`' schema and the template feedback. So every planner request, and every Critic request with findings, misses the committed cassettes. The main session re-records every session onto the branch before merge, with the owner's OK:

```bash
make record-cassettes     # every session; about $0.30
make check-cassettes      # replay every session from the cassettes alone
```

Until then, these are expected red:

- the committed-cassette convergence test (D7): the current recording's e2e runs 4 attempts;
- the images job's `python -m promopilot.cassettes --check`, where the planner's requests miss;
- the Playwright assertion that the Explainer's LLM answer explains the plan, because the planner degrades on the miss and the Explainer's request changes with it.

The Context readings are unchanged, so the rest of the committed-cassette test and the architecture grounding test stay green on the old cassettes.

## Consequences

- **New public names:**
  - `Handoff.FINDINGS_REPEATED` in agents;
  - `GenerateCandidatesInput.exclude_sku_ids`;
  - `generate_options(..., exclude_sku_ids=)` in the optimiser;
  - `loosening(..., scope_may_narrow=)`.
- There is no migration, no API contract change and no new configuration.
- The prompts are now planner v3 and critic v2.
- **What this amends:**
  - ADR 0051 D4 (a fifth handoff), D1 (the template feedback's levers), D5 (planner prompt v3) and D9 (the typical cost);
  - ADR 0049 D2: an analysis may narrow the scope.
