# The Explainer's LLM cites amounts pre-formatted in lakh or crore, is regenerated once when ungrounded, and falls back to a stored template explanation

E8 (#49) makes explanations cite only real numbers (SF-05). SPEC §9.6 says the Explainer's LLM writes a rationale per plan line and a plan summary from tool outputs, and `check_numeric_grounding` verifies every number "with tolerance for rounding". A failed check means one regeneration, then a template explanation. #44 already added that template (ADR 0046 D13), but kept it in the graph's state only.

SPEC does not fix:

- where explanations are stored;
- how money is shown;
- which numbers the LLM gets, and what grounding checks against;
- how many calls are made;
- what a regeneration sends, and how much falls back;
- what an LLM error does;
- how a fallback is shown;
- how infeasible plans are explained.

We chose these with the owner (D1–D12 on #49, every recommended option).

## Storage and read model

- **D1. One `PlanExplanation` per plan revision, stored as JSONB.** `PlanExplanation` is a domain value with these fields:
  - `summary`;
  - `rationales`, one per plan line in plan-line order (a `PlanRevision` validator enforces the count);
  - `source`, `llm` or `template`;
  - `fallback_reason`, set only for a template.

  It sits on `PlanRevision.explanation` and is stored in `plan_revisions.explanation` (migration 0012). It is null until the Explainer has run, and for revisions planned before #49. The graph's state holds the same type, and the Explainer writes it through a new `SessionRecorder.save_explanation`. The read model shows it with the revision. This supersedes ADR 0046 D13's "the explanations live in the graph's state only".
  - We rejected text columns (`plan_revisions.summary` and `plan_lines.rationale`), which need an update per line.
  - We rejected an `explanations` table, which adds a join for no present need. #50's "what changed and why" can become a field of `PlanExplanation`.
- **D12. The frontend follows the contract.** The zod schema and fixtures carry `explanation`; showing it is E10's.

## Money and what the LLM sees

- **D2. Money is shown in lakh or crore.** This carries out #43's follow-up. The formats are:
  - below ₹1 lakh, whole rupees with Indian digit grouping ("₹18,250");
  - from ₹1 lakh, lakh to at most two decimals ("₹1.72 lakh", ±₹500);
  - from ₹1 crore, crore to at most two decimals ("₹1.25 crore");
  - percentages to at most one decimal ("22.4%");
  - units as whole numbers with Indian grouping.

  Trailing zeros are dropped ("₹2 lakh"), which only widens the rounding the text shows. The template uses the same formats, which amends ADR 0046 D13's "whole rupees".
  - We rejected one-decimal lakh (±₹5,000), which blurs lines that are close in value.
  - We rejected keeping whole rupees in the template.
- **D11. The formatters live in `promopilot.guardrails`.** They are `format_rupees`, `format_percent` and `format_units`, the inverse of grounding's parser. Hypothesis properties check that each formatted value always passes `check_numeric_grounding` against the value it came from. Keeping them out of `promopilot.agents` keeps number-dividing code out of the module that must hold no business arithmetic (#47). The grounding tolerance itself is unchanged: ADR 0028 already reads "₹1.72 lakh" as ₹1,71,500–₹1,72,500.
- **D3. The LLM gets a JSON view of the tool outputs in which every amount is already a display string.** `plan_data` builds it. It includes:
  - each line with its why-chosen reasons, compared mechanisms, simulated ranges and plan-time facts;
  - the plan's simulated ranges and regional stock-out risk;
  - the binding constraints, clearance shortfalls, relaxation, policy findings and open issues;
  - the planner's notes and the options left out;
  - the planning request and company policy.

  Identifiers, week ids and counts stay as they are. Nothing is summed or divided. The prompt (`agents/prompts/explainer.md`, v1) says to copy numbers exactly as shown and never calculate. Each part of the answer is grounded against this same view.
  - The view carries display strings in place of raw values. An exact rupee figure above ₹1 lakh therefore cannot ground: the lakh/crore format is enforced by the check, not just asked for.
  - The brief is not in the view. That leaves no user text for a prompt injection to hide in.
  - We rejected giving raw numbers and asking the LLM to round, which makes it do arithmetic.
  - We rejected grounding against the raw revision only, which rejects counts such as "35 lines".
- **D4. Nothing that depends on solver time is in the view.** Time-limited re-solves settle the binding analysis differently on different machines (ADR 0038). So the view leaves out:
  - how much each binding constraint is worth (`objective_gain`);
  - its evidence;
  - constraints left `unproven`.

  The Explainer's request then hashes the same everywhere, which replay needs (ADR 0019). Proven binding constraints are still named with their limits. The template lists unproven constraints as "may also bind". We rejected giving the gains ("worth at least ₹2,241"): they are richer, but replay would miss on another machine.

## Calls, regeneration and fallback

- **D5. One structured call at temperature 0.** It returns `ExplainerAnswer`: the summary, and a `{line, rationale}` for each plan line keyed by line number. An answer counts as invalid when:
  - the summary is blank;
  - a line is missing, repeated or unknown;
  - a rationale is blank.

  An invalid answer is treated like an ungrounded one. We rejected a call per line (36 or more on the demo plan). We rejected LLM summaries with template rationales, which leaves SF-05's rationales unwritten by the LLM.
- **D6. One regeneration of the whole answer, then the whole template.** The regeneration sends the failed answer back, followed by a message naming each problem: the ungrounded numbers of each part as written, or the structural fault. At temperature 0 the same request would repeat the same answer (and the same hash). A second failure makes the whole explanation the template, with `fallback_reason` `ungrounded` or `invalid_answer`.
  - We rejected keeping the grounded parts and templating only the failing ones, which needs provenance per part.
  - We rejected regenerating only the failing parts, which complicates prompts and cassettes.
- **D7. An LLM error falls back at once.** Any `LLMError` that survives the retries and fallback provider (ADR 0027) makes the template explain the revision with `fallback_reason` `llm_unavailable`. This includes a `CassetteMissError` in replay. There is no regeneration, and the session still reaches Approval. #47's "LLM down gives the degraded plan with template explanations" relies on this.
  - **This amends ADR 0027's "a cassette miss must fail loudly" for the Explainer.** Until #51 records full-graph cassettes, the replayed Docker stack and the Playwright journey reach Approval with template explanations. The miss is still visible: a warning log and `fallback_reason`. #51's check over recorded sessions should assert that they do not fall back.
  - We rejected failing the session on a cassette miss, which keeps the stack red until #51.
  - We rejected an "LLM down" flag from #47's planner that skips the Explainer's call; it couples the two tickets and can come later.
- **D8. A fallback is visible.** It shows in three places:
  - `source` and `fallback_reason` in the read model;
  - a structured `explainer_fallback` warning log with the session id, revision number and reason;
  - a trace event, added by #45 or by this ticket, whichever merges second.

## Infeasible and policy-bound plans

- **D9. Deterministic sentences open the summary.** For an `INFEASIBLE` revision, or when the relaxation says company policy binds, the summary opens with the template's constraint sentences. The LLM's summary follows. The constraint sentences name:
  - each binding constraint with its limit ("the clearance target for SKU0029 in North at 90%");
  - each clearance shortfall;
  - each relaxation change, from the brief's value to the relaxed one ("the clearance target for SKU0029 from 90% to 70.3%", or "drop …");
  - that company policy binds, and the most sell-through policy allows.

  AG-06's explanation therefore never depends on the LLM's wording. The template always carries the same sentences.
  - We rejected relying on the prompt alone.
  - We rejected checking the LLM's wording for each constraint name, which is brittle.
- **Planner notes.** `PlanningState.planner_notes` holds deterministic sentences from #47's planner, such as "the language model was unavailable" or a KVI-undercut response. They go into every summary verbatim:
  - after the D9 sentences and before the LLM's summary;
  - after the constraint sentences and before the open issues in the template.

  They are also in the LLM's view, so an answer that repeats their numbers still grounds.

## Tests

- **D10.** Graph tests script the Explainer's LLM with `FakeProvider`, and cover:
  - a grounded answer is stored;
  - an ungrounded first answer is regenerated once, naming its numbers;
  - a second ungrounded answer yields the template;
  - an invalid answer is regenerated, and a second invalid one yields the template;
  - an `LLMError` or `CassetteMissError` yields the template without a regeneration;
  - an infeasible summary opens with what binds;
  - an exact rupee figure above a lakh does not ground, while the lakh form does;
  - the request hash does not change with what the binding analysis had time to prove.

  Tests that are not about the Explainer script `explainer_down()` (`tests/unit/agents/fakes.py`), an `LLMError` that yields the template. A `FakeProvider` whose script runs out still fails loudly. The template's hypothesis property still checks that its explanations always pass grounding against the revision.

## Consequences

- **Migration 0012** adds `plan_revisions.explanation`.
- **New public names:**
  - domain: `PlanExplanation`, `ExplanationSource`, `FallbackReason`;
  - agents: `explain_plan`, `ExplainerAnswer`, `LineRationale`;
  - guardrails: the three formatters;
  - `SessionRecorder.save_explanation`.

  `agents.Explanations` is replaced by `PlanExplanation` (its `lines` are now `rationales`). The graph's state gains `planner_notes`.
- **Cassettes (#51).** The Explainer's LLM call only happens after planning, so recording its cassettes needs the loaded data and a trained model. This amends ADR 0022 and ADR 0038's "plans are never recorded; recording needs no trained model" for #51. This ticket records no cassettes. The committed-cassette test replays only the brief reading and is unchanged.
- **Cost and latency.** The Explainer adds one call, or two with a regeneration. Its output grows with the plan: the demo plan has 35 lines.
- **No new configuration.**
