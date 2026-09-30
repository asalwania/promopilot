# The Planner is an LLM agent over the tool registry whose plan is its last optimiser result, and it falls back to the default sequence when it cannot reach one

E8 (#47) makes the Planner an agent (AG-03). It calls `complete_with_tools` over the tool registry, chooses the analyses and the optimiser options, and never computes a number. Every tool call is traced. Tool errors are retried, then reach the LLM as structured errors. If the LLM is unavailable after its retries and fallback, the deterministic default sequence plans instead (SF-03).

SPEC §9.6, #10 and #47 leave open:

- where the final plan comes from;
- what the LLM may change in the planning request;
- how the planner "responds" to an undercut KVI, and how it explains that;
- the loop's bounds, the retry policy and exactly when to degrade;
- how tool-calling cassettes replay;
- the rule of the "no business arithmetic" architectural test;
- how tracing plugs into #45.

We chose these with the owner (D1–D13 on #47; every recommended option).

## The plan

- **D1. The plan is the latest successful `run_optimizer` result.**
  - `run_optimizer` now records its `OptimisationResult` with the candidate set (`CandidateStore.record_solution`).
  - `StoredRevisions` builds the plan revision in process from the stored set and that solution, through `OptimisingPlanner.revise`: each line's mechanism comparison, a simulation with the session's settings, and the plan facts. `plan` and `revise` share that code, so an agent's plan and the default sequence's plan of the same candidate set are the same revision.
  - Nothing is parsed back from tool JSON, as ADR 0046 D12 asked.
  - The LLM calls `simulate_plan` only for what-ifs, such as a competitor reaction. It never has to copy the plan's lines into a call.
  - We rejected a structured "final answer" naming the candidate set to adopt, which costs one more step and adds a way to fail. We also rejected solving the last set again in the builder, which adds another 6–14 s solve.
- **D2. The LLM passes the planning request on, and may only tighten the optimiser options.**
  - The brief's constraints are fixed: as-of week, scope, promo window, marketing budget, minimum margin and clearance targets.
  - The optimiser options may be added or tightened, never loosened:
    - a regional budget cap may be added or lowered;
    - the KVI price tolerance may be turned on or narrowed;
    - the promoted-SKU cap may be added or lowered.
  - `loosening(given, proposed)` names each change that breaks this. The planner refuses such a `generate_candidates` or `compare_mechanisms` call with a structured `invalid_input` error before it reaches the tool.
  - The session keeps the Context agent's request, and the Critic validates against it.
  - We rejected letting the LLM pass only the request as read, which leaves the issue's optimiser options out. We also rejected accepting any change: the Critic would catch a budget breach but not a changed scope or window.
  - **Amended by ADR 0084:** besides the request, the planner may cap one SKU's depth or mechanisms with `generate_candidates`' `sku_limits`. The tool refuses a limit that would loosen company policy or the call as `invalid_input`.
- **D3. No new undercut lever.**
  - Price matches are always offered (ADR 0040), and the optimiser takes one when it pays for itself.
  - The LLM's levers are the KVI price tolerance and the generation filters.
  - The issue's "soft constraints" have no lever either: ADR 0040 already makes every clearance target hard, then soft with a reported shortfall.
  - We rejected a `price_match` switch on `generate_candidates` and a hard "respond to undercuts" optimiser constraint (new constraint, relaxation and binding work).
- **D4. The undercut explanation is a template from `get_competitor_gaps` (F-08 AC2).**
  - After the plan is chosen, on both the agent and the degraded path, the planner calls `get_competitor_gaps` for the scope's KVIs through the registry, so the call is traced.
  - `CompetitorGaps.undercut_response(lines)` in `promopilot.competitors` writes one sentence per undercut KVI, widest gap first, for example "Competitor is 5.1% cheaper on SKU0002 (…) in North (₹94.90 vs ₹100.00)."
  - It then writes "Matching on N SKUs: …", or "Not matching on any undercut SKU: no price match paid for itself …, so the plan protects margin."
  - A KVI counts as matched when a plan line in its region promotes it at an effective unit price at or below the competitor's, so a deeper discount counts too.
  - The formatting and the price comparison live in `competitors`, outside the agents package. Every number comes from the gaps, and a test checks that the sentences pass numeric grounding against them.
  - The sentences are the revision's **planner notes** (`PlanningState.planner_notes`). #49's Explainer puts them verbatim in every summary, the LLM's and the template's (ADR 0050).
  - We rejected LLM-written sentences checked by grounding with a template fallback, which duplicates #49 and needs cassettes. We also rejected waiting for #49's Explainer.

## Bounds, errors and degradation

- **D5. At most 8 LLM steps and 16 tool calls per planning** (`MAX_STEPS` and `MAX_TOOL_CALLS`, set in `AgentTools`).
  - A restart's steps count towards the 8.
  - A step's tool calls run one after another, in order.
  - Results go back as compact JSON: `{"ok": true, "output": …}` or the error.
  - At either limit the planner uses the latest optimiser result, or degrades when there is none.
  - The estimated cost is about 110k input tokens: about ₹4 on `gpt-4.1-mini`, and about ₹22 if the `claude-sonnet-5` fallback answers. SPEC §6's ₹20 per session is measured in E9 and tuned in E11.
  - We rejected 12 steps and 24 calls (about ₹7, or ₹35 on the fallback), and adding a token budget from the usage meter.
- **D6. A tool that raises is retried; a `ToolError` is not.**
  - The registry's own errors (`invalid_input`, `unknown_tool`, `model_unavailable`, `data_unavailable`) are deterministic. They reach the LLM at once, for it to correct its call.
  - Any other exception from a tool is retried: three attempts, waiting 0.5 s then 1 s through an injected sleep, around the traced registry call. Each attempt is therefore its own trace event.
  - After the last attempt, the exception reaches the LLM as `ToolError(code="tool_failed")`, naming the tool and the error. It is logged with its traceback.
  - This amends ADR 0025's "a bug in a handler still raises", for the planner's calls only. The registry itself still raises.
  - We rejected retrying every error, which is pointless for deterministic ones, and never retrying.
- **D7. When the default sequence plans instead.** The planner discards the agent's work and runs `OptimisingPlanner.plan` when:
  - the LLM raises `LLMError` at the first step. The provider has already retried and fallen back (ADR 0027).
  - it raises after tool rounds, and one restart of the conversation from the start fails too. The restart is ADR 0027's fix for a fallback provider that rejects another provider's open tool round.
  - replay has no cassette. This is `CassetteMissError`, with no restart (D9).
  - the LLM stops without a successful `run_optimizer`, even after one reminder.
  - a limit is reached with no optimiser result.
  - the solved set is no longer stored.

  `PlanningState.planner_degraded` records why, as a `DegradedReason`: `llm_unavailable`, `cassette_missing` or `no_optimised_plan`. The first planner note says so, for example "The language model was unavailable, so the default sequence (generate candidates, optimise, simulate) planned this revision." Errors from the default sequence itself (`PlanningError`) still fail the session (ADR 0046 D14). There is no read-model or migration change.

  We rejected reusing a partial candidate set, which makes "degraded plan" ill-defined, and degrading on any `LLMError` with no restart.
- **D8. The Context node still needs the LLM.** A total outage fails the session at Context (ADR 0046 D14), before the Planner runs. So SF-03's "the deterministic optimiser still runs if the LLM is down" holds from the Planner on. A deterministic Context fallback on `BriefResolver` is a follow-up issue, after #46.

## Cassettes

- **D9. Tool rounds replay on any machine, and the planner degrades on a miss.**
  - Tool results carry things that change on every run:
    - a candidate set's id;
    - every model's id, which changes with each `make train`;
    - binding evidence, which depends on the machine.
  - So:
    - **The tool-request hash leaves out the content of `tool` messages.** Tool names, arguments and call ids stay in. This amends ADR 0027. No tool cassette existed, so no committed hash changed.
    - **A candidate set's id is deterministic**: a uuid5 of the call's arguments, the as-of week and the demand and relations model versions (not their ids). A replayed `run_optimizer` then finds the set the replayed `generate_candidates` made. Two sessions with the same call share the id. The later store replaces the set with an identical one and forgets its solution.
    - **A `CassetteMissError` in the planner degrades** (D7), with a loud `planner_cassette_miss` log naming the hash, so `make demo` and the e2e journey plan until the planner cassettes are recorded. This amends ADR 0027's "a cassette miss must fail loudly" for the Planner only. The Context agent's miss still fails the session.
  - **`make record-cassettes` plans each brief with the planner agent**, recording its tool-calling steps. It now needs `make data` and `make train` first, which amends ADR 0038's "recording needs no trained model". A brief the agent cannot plan without degrading fails the run and changes nothing. The API and the recorder build the same tools (`promopilot.api.planning.build_planning`).
  - We rejected keeping the exact hash and degrading on a miss: the demo would degrade on every fresh clone. We also rejected keeping it and failing loudly: the demo and e2e would break until recorded, and again after any retrain.

## Architecture and tracing

- **D10. `promopilot.agents` has no business arithmetic, checked on its syntax.**
  - `tests/architecture/test_agents_have_no_business_arithmetic.py` walks the package's AST, leaving out `promopilot.agents.tools`, which is the compute seam (ADR 0025).
  - It refuses:
    - arithmetic operators, augmented ones included, unless an operand is text or a list;
    - `sum`, `round`, `abs`, `min` and `max`;
    - imports of `math`, `statistics`, `numpy`, `decimal`, `fractions` and `scipy`.
  - The existing uses are listed, each with its reason: `resolution.py`'s phrase scores, the explainer's whole-rupee display, the week table's range, the Planner's iteration counter and a cassette path.
  - SPEC §13.4 also enforces the rule by grounding checks over recorded sessions. Those run with #49's Explainer and E9's evals.
  - We rejected moving the tools out of the package, a refactor that collides with parallel E8 tickets.
- **D11. Tracing is #45's.**
  - The planner makes every tool call through `ToolRegistry.call`, which #45 wraps to emit a `tool_called` event, and adds no tool-call events of its own.
  - Its decisions (restart, limit, degraded, refused call) go through `_decide`. That only logs until #45's `emit` lands, and then emits `decision` events.
  - The acceptance test records calls through a traced registry that stands in for #45's wrapper.
- **D12. The LLM is offered all 11 SPEC §9.6 tools**, which is exactly the registry. We rejected a smaller set to save schema tokens.
- **D13. The agent is on when `GraphTools.agent` is set.**
  - The API always sets it, from `build_planning`.
  - Without it, the graph runs the default sequence, as in ADR 0046, so the earlier graph and API tests are unchanged.
  - There is no new setting.
  - We rejected a `PLANNER_AGENT` flag.

## Consequences

- There are new public names:
  - agents: `AgentTools`, `plan_with_tools`, `loosening`, `StoredRevisions`, `DegradedReason`, `RecordedPlanning`, and the `ToolCaller`, `RevisionSource` and `DefaultSequence` protocols;
  - competitors: `CompetitorGaps.undercut_response`;
  - optimizer: `CandidateStore.record_solution` and `CandidateStore.solution`;
  - api: `promopilot.api.planning`.
- `PlannedRevision` gains `notes` and `degraded`. `PlanningState` gains `planner_notes` and `planner_degraded`. `ToolErrorCode` gains `tool_failed`.
- The prompt is `agents/prompts/planner.md`, planner v1. The brief is passed as a quoted JSON string next to the planning request.
- There is no migration and no API contract change. The planner notes reach the read model with #49's stored explanations.
- **Cassettes to record** (the main session records them with the owner's OK; nothing was recorded against a live LLM here). After `make data` and `make train`, `make record-cassettes` re-records:
  - the Context reading of the demo brief in `briefs.json` (unchanged hash);
  - one tool-calling step per planner turn for that brief, typically 4–6 files: `get_competitor_gaps`, then `generate_candidates`, then `run_optimizer`, optionally `compare_mechanisms` or `relax_constraints`, then the closing text.

  Until then the demo and e2e sessions plan through the default sequence with a `cassette_missing` note.
- Follow-ups:
  - #48 sends Critic feedback to the planner;
  - a deterministic Context fallback;
  - #45 wires `_decide` to `emit`;
  - #49 includes the planner notes in its summaries and stores them;
  - E9 and E11 measure and tune the per-session cost.
