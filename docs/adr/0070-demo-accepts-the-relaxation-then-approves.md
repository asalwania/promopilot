# The demo script accepts the relaxation and then approves, and the recorder follows the API's rules

#149 makes the recorded `demo` session end the way SPEC §12 and the demo video end: approved. It is also the way the UI can end it.

Every demo revision (1–3) was `INFEASIBLE`: no plan reaches the 60% clearance target on SKU0006, the 400g namkeen. `POST /approve` answers 409 on an infeasible revision (ADR 0046 D10). The recorder approved the demo by calling `resume_with_decision` directly, which skips that check. So the recorded demo "approved" a revision the UI cannot approve, and the Playwright demo journey stopped at "Approve disabled" (ADR 0066 D11).

The ticket, SPEC and ADR 0054 leave open:

- the step's shape in `sessions.json`;
- whether the recorder goes through the API's rules;
- where the accept step goes;
- what happens if the relaxed revision is still infeasible;
- how `--only` re-records a session that gains a step, without re-asking its earlier rounds;
- how the committed-cassette test learns the accepted text;
- how the Playwright journey changes.

We chose these with the owner (D1–D8 on #149; every recommended option).

## Decisions

- **D1. The demo script is plan → "Budget cut to ₹6 lakh" → "Drop West" → `{"accept_relaxation": true}` → approve.**
  - `ScriptStep` gains `accept_relaxation`. A step is still exactly one of `answers`, `amend`, `accept_relaxation` or `approve`. The step mirrors `/amend`'s body (ADR 0052 D7).
  - The accept step goes after "Drop West". A request depends only on the brief, the steps before it and the prompts, so rounds 1–3 keep their request hashes and their 25 cassettes. The old approve step made no LLM call.
  - We rejected nesting the step as `{"amend": {"accept_relaxation": true}}`, which breaks `amend`'s string shape.
  - We rejected a literal `{"amend": "Accept the smallest relaxation: …"}`. It hard-codes a number the optimiser computes, goes down the text path and stores no `Relaxation` on the amendment.
  - We rejected accepting after revision 1. Every later Context request would carry the relaxation, so rounds 2 and 3 would need re-recording, and the budget cut could make the plan infeasible again.
- **D2. The recorder and `--check` follow the API's two rules**, which `promopilot.agents` now holds once:
  - `approval_refusal(revision)`: an `INFEASIBLE` revision is never approved.
  - `acceptable_relaxation(revision)`: only a relaxation with changes can be accepted.

  `SessionService` and the recorder both call them.
  - An accept step sends `relaxation_amendment(relaxation)` through `resume_with_amendment`, as `SessionService.amend` does.
  - An approve step on an infeasible revision is a problem ("step 4 approves plan revision 3, which is infeasible: accept its relaxation first"). So is an accept step on a revision with no relaxation. The recording then fails and changes nothing (ADR 0054 D8), and `--check` names it.
  - The recorder still drives the graph with an in-memory session store. We rejected driving `SessionService` with fakes of the store and the checkpointer: too much machinery for two rules.
- **D3. A relaxed revision that is still infeasible fails the recording.** The approve step is refused as in D2. The main session then decides, for example by adding a second accept step.
  - We rejected a script that loops "accept until feasible": the script would no longer be fixed.
  - We rejected lowering the brief's 60% target, which departs from SPEC §3.2.
- **D4. `--only` answers every request the named sessions recorded before from its cassette.** `record_cassettes` copies the named sessions' previously listed cassettes into its scratch directory, as it already did for the kept sessions (ADR 0054 D12).
  - A session that gains a step asks the live model only for the new round, and its earlier rounds replay byte for byte.
  - To ask an unchanged request afresh, delete its cassette first.
  - A request whose prompt, schema or data changed has a new hash, so it still goes live.
  - Without this, `ONLY=demo` would re-ask all four rounds. That costs about four times as much, and its new answers would overwrite rounds 1–3.
  - We rejected an explicit `--extend` flag: one more option for what re-recording should do anyway.
- **D5. The manifest records each session's amendment texts.** `RecordedSession.amendments` holds them in order: each scripted amendment, and each text an accept step wrote from its relaxation.
  - The committed-cassette test replays each Context reading of a session with those texts, since an accepted relaxation's text comes from the plan.
  - Older manifest entries read it as empty.
  - We rejected skipping accept steps in that test, which would leave the round covered only by the images job.
- **D6. `amend.spec.ts` plays the whole demo**, extended in place:
  - revision 1's approval is disabled, and its binding clearance target, relaxation and accept button show;
  - the two amendments each show their diff;
  - revision 3's approval is disabled, and **Accept the relaxation and re-plan** re-plans;
  - revision 4's diff names the amendment and a clearance-target request change;
  - approval with its confirmation makes the session **Approved** and **Final**;
  - the audit trail lists both amendments, the accepted relaxation (badged) and "Approved plan revision 4".

  Through the API it checks:
  - the session is `approved`;
  - the third amendment carries its relaxation;
  - revision 4 is not `INFEASIBLE`, its diff is from revision 3, and the Explainer's recorded answer explains it.

  The test's timeout grows to four planning rounds. `approve.spec.ts` stays on the `e2e` session. We rejected a separate demo spec, which would replay the first three rounds twice in CI.
- **D7. The demo example's hint** reads "Then amend with “Budget cut to ₹6 lakh” and “Drop West”, accept the relaxation, and approve." SPEC is unchanged: §18's demo already ends in approval.
- **D8. This PR carries the code, the tests and the script, but no recording** (as ADR 0054 D10). The main session records onto the branch with the owner's OK. Until then, these are expected red:
  - the committed-cassette test (the demo was recorded with another script, and has no amendment texts);
  - the images job's `--check`;
  - the Playwright demo journey.

## Is the relaxed revision feasible?

The accept round's plan depends on the live LLM, so nothing short of recording proves it. A probe with no LLM checked the deterministic part:

- It ran on an isolated database with `make data` and `make train`.
- It replayed the demo to revision 3 from the committed cassettes, with no miss and no fallback. Revision 3 was `INFEASIBLE` with objective ₹16,877.89, as recorded.
- Revision 3's relaxation is proven, and policy binds. It lowers SKU0006's clearance target from 60% to 59.86%, which is what policy allows. The accept step's text is "Accept the smallest relaxation: lower the clearance target for SKU0006 to 59.86% sell-through."
- The probe applied it with `optimizer.relaxed_request` and planned with the default sequence. The result is `OPTIMAL`: 20 lines, objective ₹83,823.02 and no clearance shortfall.

What remains is the LLM's part:

- the Context agent must lift 59.86% exactly and keep North, ₹6 lakh, 18% and SKU0002's 60%;
- the planner agent must plan the same candidates the probe planned;
- the Critic must not push a worse attempt.

A failure there fails the recording (D3).

## Recording

From the repository root in Git Bash, with `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-4.1-mini` in `.env`, after `make data` and `make train`:

```bash
make record-cassettes ONLY=demo   # asks the live model only for the accept round
make check-cassettes              # every session replays, the demo to its approval
```

Expect about 5–8 live calls and a few cents: one Context reading, the planner agent's steps, perhaps the Critic, and the Explainer.

Afterwards:

- `git status backend/cassettes` should show `manifest.json` modified and only new cassette files;
- the demo's `cassettes` in the manifest should begin with its 25 earlier ones, in the same order.

A seeded cassette is never rewritten. If an earlier cassette was removed instead, rounds 1–3 asked other requests than they recorded, so they no longer planned as recorded on this host. Discard the recording and find out why before re-recording the whole demo.

## Consequences

- **New public names:**
  - agents: `approval_refusal`, `acceptable_relaxation`, `ScriptStep.accept_relaxation` and `RecordedSession.amendments`.
- **Changed:**
  - `record_cassettes(..., only=...)` answers the named sessions' earlier requests from their cassettes (D4);
  - `SessionService` uses the shared rules, with its 409 messages unchanged.
- **This amends:**
  - ADR 0054 D1 (the demo is taken to a feasible revision before approval);
  - ADR 0054 D2 (the fourth step kind);
  - ADR 0054 D3 (`--only` asks live only what is new);
  - ADR 0066 D11 (the demo journey approves).
- No migration, no API contract change and no new configuration.
- AG-06 (infeasible → relaxation → accept) is now visible end to end in the demo.
