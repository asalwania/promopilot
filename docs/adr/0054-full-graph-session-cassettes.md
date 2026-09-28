# Cassettes record scripted sessions through the full agent graph, listed in a manifest, checked for grounding offline and replayed in CI

E8 (#51) makes whole agent sessions replay with no key. `make record-cassettes` records the full graph for the demo and e2e briefs, including a clarification. The composed-stack Playwright journey passes with the new graph, and grounding checks run over the recorded sessions (SPEC §13.4).

Until now the recorder read each brief and ran one planner attempt. It never recorded the Critic, the Explainer, a clarification or an amendment. So in replay every later call missed, and the stack fell back to the default sequence and the template explanation (ADR 0049 D9, ADR 0050 D7, ADR 0051).

SPEC, #10 and #51 leave open:

- which sessions are recorded, and where their answers and amendments live;
- how the recorder drives the graph, and how cassettes are named and pruned;
- how the grounding test finds the recorded sessions;
- how CI proves whole sessions replay;
- what happens to the cassette that was migrated by hand.

We chose these with the owner (D1–D11 on #51; every recommended option). D12 records what the first live recording taught.

## Decisions

- **D1. Three sessions are recorded.**
  - `e2e` is the ADR 0022 brief (₹2 lakh, North and West, Snacks and Beverages), taken to a plan.
  - `demo` is the SPEC §3.2 brief (₹8 lakh, margin above 18%, 400g namkeen at 60%, families), which joins now as ADR 0048 planned. It is taken to a plan, amended with "Budget cut to ₹6 lakh", amended with "Drop West", and approved.
  - `clarify` is the e2e brief without its budget. The Context agent asks for `marketing_budget`, the script answers "₹2 lakh", and the session plans. Its request then matches the e2e one, so the two sessions share their Explainer cassette.
  - An infeasible brief is left to E9/E11. It is one more entry in the scripts file. We rejected recording it now: it adds a round and a risk that the planner degrades.
- **D2. Scripts live in `backend/cassettes/sessions.json`**, which replaces `briefs.json`.
  - It is a list of `{name, brief, steps}`. Each step is exactly one of `{"answers": {question_id: text}}`, `{"amend": text}` or `{"approve": true}`.
  - Question ids are field names, such as `marketing_budget` (ADR 0048).
  - `promopilot.agents.load_scripts` reads the file and refuses duplicate names or a step that does two things.
  - Playwright reads the `e2e` entry, and E10/E11 can prefill the demo from the file.
- **D3. Cassettes stay flat and hash-named (ADR 0019), next to `backend/cassettes/manifest.json`.**
  - The manifest lists, per session: its script, its route (nodes and interrupts in order), the request hash of every LLM call in call order, and each plan revision with its explanation source. It also holds the planning settings (D11).
  - After a recording, every hash file that no session lists is removed.
  - `--only NAME` (`make record-cassettes ONLY=name`) re-records the named sessions and keeps the others' recording. The others must have been recorded with the same planning settings.
  - `manifest_problems` checks, without replaying, that:
    - every script was recorded as it stands;
    - every listed cassette exists;
    - no cassette is orphaned.
  - We rejected replace-all with no manifest: one bad live answer would mean a full re-run, and an edited script could not be caught offline. We rejected one subdirectory per session: replay's lookup would change, and shared requests would be duplicated.
- **D4. The grounding test reads the cassettes themselves.**
  - `ungrounded_answers(cassettes)` runs `check_numeric_grounding` over each shown Explainer answer (summary, every rationale and `changes`), against the plan data in its own request. An answer later regenerated is skipped, because it was never shown.
  - It also checks every Critic feedback against the finding it words, as the Critic does (ADR 0051 D1).
  - `tests/architecture/test_recorded_sessions_are_grounded.py` runs it over the committed cassettes. It also asserts that the manifest records every revision as explained by the LLM, which settles ADR 0050 D7's "should assert that they do not fall back".
  - It needs no model and replays nothing.
  - We rejected replaying every session in the unit lane: minutes per session, and exposed to differences between machines. We rejected storing outputs separately, which duplicates what the cassettes hold.
- **D5. CI replays whole sessions in the images job.**
  - After loading data and training, `docker compose exec -T api python -m promopilot.cassettes --check` plays every script through the full graph on the cassettes alone. It fails on:
    - a miss;
    - a fallback;
    - another route than the recording's;
    - planning settings that differ from the recording's.
  - The Playwright journey stays brief → plan (the amend, approve and clarify UI is E10's). It types the `e2e` brief and then asserts, through `GET /api/sessions/{id}`, that the Explainer's LLM answer explains the plan. This proves the served path (Postgres checkpointer, session store) replays too.
  - If `--check` flips between CI runs, it becomes report-only.
- **D6. A candidate set's id no longer depends on model version numbers.** This amends ADR 0049 D9.
  - The uuid5 now covers the call's arguments, the as-of week and each model's training as-of week.
  - With version numbers, a planner round recorded on demand v5 / relations v2 named a candidate set that CI, a fresh clone and `make demo` (all v1 / v1) never stored. So every replayed `run_optimizer` failed, and the planner degraded.
  - A retrain in the middle of a session may hand `run_optimizer` the newer model's set. That is rare and harmless.
  - No committed cassette changes: no planner cassette was committed.
- **D7. Recording runs on the host** with `make record-cassettes`, as before. Since ADR 0055, every optimiser phase stops on a deterministic-time budget, so a plan does not depend on how fast or busy the machine is; before it, a slower or loaded machine planned the demo differently (#133). CI's `--check` catches any remaining drift between the Windows host and the Linux containers. If drift shows, recording moves into the api container, in an isolated compose project with its own volumes. Never record against the shared database: training in the container would register models whose artifacts the host cannot load.
- **D8. A recording fails, and changes nothing, when any session:**
  - has the Context agent read by rules;
  - asks a question the script does not answer, or not the ones it answers;
  - reaches a step the graph is not waiting for;
  - has the planner agent fall back to the default sequence in any attempt;
  - has the Explainer fall back to its template, including after a regeneration;
  - records Critic or Explainer text that `ungrounded_answers` rejects.

  Reaching the Critic's cap with open issues is allowed.
- **D9. The hand-migrated cassette `9c322147…` (ADR 0048 D12)** is the `e2e` session's first Context request. The prompt is unchanged, so a live recording rewrites it under the same hash. It is superseded, not special-cased.
- **D10. This PR carries the code, the tests and `sessions.json`, but no recording.** Recording needs a live key and the owner's OK, so the main session records onto the branch before merge. Until then, these are expected red:
  - the committed-cassette test;
  - the architecture grounding test;
  - the images job's `--check`;
  - the Playwright assertion that the LLM explained the plan.

  We rejected skipping sessions with no manifest entry, which hides gaps. We rejected splitting the code and the cassettes into two PRs.
- **D11. The manifest records the planning settings** that shape what the LLM is shown:
  - the optimiser's work budgets, which decide the plan (ADR 0055): `OPTIMIZER_DETERMINISTIC_LIMIT`, `OPTIMIZER_BINDING_DETERMINISTIC_LIMIT` and `OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT`;
  - their wall-clock safety nets, which matter only on a machine that reaches one: `OPTIMIZER_TIME_LIMIT_SECONDS`, `OPTIMIZER_BINDING_TIME_LIMIT_SECONDS` and `OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS`;
  - `OPTIMIZER_WORKERS` and `OPTIMIZER_SEED`;
  - `SIMULATION_RUNS` and `SIMULATION_SEED`;
  - the four `CRITIC_*` thresholds.

  `--check` names any that differ on the replaying stack. `Planning.recorded_settings` lists them, and `Planning.recorded()` builds what the recorder and the check play with.
- **D12. One answer per request, and no raw floats in a request.** The first live recording (58a5fe4) replayed e2e and the demo on Windows. clarify missed there, and e2e and clarify both missed on Linux. There were two causes, both found without live calls:
  - **The same request asked twice got two answers.** The Critic reviewed an identical plan in several attempts, and in both e2e and clarify, so it was asked the identical request several times. gpt-4.1-mini worded its feedback differently across those calls, even at temperature 0. Each later planner attempt opened with whichever wording it had been given, but the cassette kept only the last one written. So on replay, an attempt opened with the other wording and missed.
    - `RecordingProvider` now answers a request already recorded in its directory from that cassette, without asking the live model again. It then reports no usage.
    - With `--only`, the kept sessions' cassettes are copied into the recording's scratch directory first, so a request a kept session shares keeps its answer.
  - **Raw floats differed between machines.** The planner's feedback message dumped each finding whole, including its raw `actual` share (0.5183146894877728 on the Windows recording, 0.5183146894877586 on Linux-trained models). So on Linux every loop-back request missed. The Critic's and Explainer's requests were unaffected, because they carry only formatted numbers (ADR 0050). The feedback message now leaves out `actual` and `limit`: each finding's message already states them as they may be cited.
  - Both change only the requests of planner attempts after the first, so e2e and clarify, which looped, need re-recording (`make record-cassettes ONLY="e2e clarify"`). The demo never looped back, and it replays on Linux as recorded.

## Recording

From the repository root in Git Bash, with `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-4.1-mini` in `.env`, after `make data` and `make train`:

```bash
make record-cassettes               # every session; ONLY="demo" re-records one
make check-cassettes                # replay every session from the cassettes alone
```

It writes the cassettes and `manifest.json` to `backend/cassettes/`, and prints each session's route, its cassette count and the live cost. Our estimate:

- five planning rounds;
- roughly 0.3–1.9 million input tokens;
- $0.3 typical and under $1 at worst (₹25–85);
- 10–20 minutes, dominated by the optimiser.

## Consequences

- **New public names:**
  - agents: `SessionScript`, `ScriptStep`, `load_scripts`, `CassetteManifest`, `RecordedSession`, `RecordedRevision`, `MANIFEST`, `read_manifest`, `manifest_problems`, `check_cassettes` and `ungrounded_answers`;
  - api: `Planning.recorded_settings` and `Planning.recorded()`.
- **Changed:** `record_cassettes(scripts, live, data, cassette_dir, planning, *, only=None)` replaces the brief list, and `RecordedPlanning` gains the policy, the Critic thresholds and the settings.
- `python -m promopilot.cassettes` takes `--sessions`, `--only` and `--check`. `make check-cassettes` is new. The images job gains a replay step.
- There is no migration, no API contract change and no new configuration.
- **What this supersedes:**
  - ADR 0022: the `briefs.json` list and its replace-all recording;
  - ADR 0048: "every brief in `briefs.json` must read without a question";
  - ADR 0049 D9: the version-number part of the candidate set id.
- **ADR 0059** changes the planner (v3) and Critic (v2) prompts, `generate_candidates`' schema and the risk review's template feedback, so every session is re-recorded. The committed-cassette test also checks that no recorded planning round runs the planner to the Critic's cap.
- A prompt, schema, calendar, model or planning-setting change needs a new recording. Once a recording exists, the committed-cassette test catches Context-level staleness in the backend job. `--check` catches the rest in the images job.
