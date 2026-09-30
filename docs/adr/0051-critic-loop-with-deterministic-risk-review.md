# The Critic finds risks deterministically, has the LLM word only the feedback, and loops a planner-agent plan back at most 3 times before the best attempt goes on

E8 (#48) makes plans fix themselves (AG-04). After `validate_plan`, the Critic reviews the plan's risks: over-concentration, heavy cannibalisation and stock-out risk. Violations and risk findings go back to the Planner with specific feedback, at most 3 times. After that, the best feasible plan goes to the Explainer with its open issues listed. For an infeasible request, the result names the binding constraints and the relaxation (AG-06).

SPEC §9.6, #10 and #48 leave open:

- how the risk review finds risks without the LLM computing numbers;
- the thresholds;
- what a finding looks like, and where the open ones are stored;
- which findings loop back;
- how feedback reaches the planner agent;
- what the default sequence does with feedback;
- which attempt is "the best feasible plan";
- which attempts become plan revisions;
- the planner's limits across attempts;
- whether the Planner must call `relax_constraints` itself.

We chose these with the owner (D1–D10 on #48; every recommended option).

## The risk review

- **D1. Deterministic checks find the risks, and the LLM only words the feedback.**
  - `guardrails.review_risks(revision, facts, request, thresholds)` finds every risk and computes every number. Each `RiskFinding` has a message with the numbers that show it and **template feedback** that names the planner's levers.
  - The Critic's LLM (`complete_structured`, `prompts/critic.md`, critic v1) rewrites the feedback of each risk finding. It is shown the findings alone as JSON: number, code, message, template feedback, SKU, region and category.
  - Its wording is kept only if it writes one non-blank feedback for every finding and `check_numeric_grounding` accepts each one against that finding. Otherwise every finding keeps its template feedback. The same happens when the LLM is down or replay has no cassette. There is no regeneration, and the session never fails on it.
  - The LLM is not called when there are no risk findings, so a clean plan needs no cassette.
  - Violations keep their own message as their feedback; the LLM does not see them.
  - **This narrows SPEC §9.6's "LLM reviews risks (…) and writes actionable feedback"** to the wording. It keeps the Critic "deterministic first, LLM second", and the LLM never computes a number (ADR 0002).
  - We rejected deterministic checks with template feedback only, which drops the LLM from the Critic. We also rejected a free LLM review with grounding: the LLM would judge the numbers, and loops would become non-deterministic.
  - **Amended by ADR 0084:** the template feedback for a finding about one SKU leads with capping its depth or mechanisms with `generate_candidates`' `sku_limits`.
- **D2. The thresholds**, `CRITIC_*` settings in `config.py` and `.env.example`, built into `RiskThresholds` by `build_planning`:
  - **Over-concentration.** A plan line above `CRITIC_LINE_SPEND_SHARE` (25%) of the plan's promo spend. The line check is skipped when the plan has fewer than 1 / threshold lines, because one of them must then take more. Also a category or region above `CRITIC_GROUP_SPEND_SHARE` (80%) of the spend when the scope has more than one.
  - **Heavy cannibalisation.** A plan line whose cannibalised profit is at least `CRITIC_CANNIBALISATION_SHARE` (50%) of its incremental profit. Both come from the line's own option in its mechanism comparison (ADR 0041). Lines with no positive incremental profit are skipped, because they are in the plan for their halo or clearance value.
  - **Stock-out risk.** A plan line whose simulated stock-out probability (ADR 0042) is at least `CRITIC_STOCKOUT_PROBABILITY` (0.20).
  - Findings come in this order: concentration (lines, then categories, then regions), then cannibalisation, then stock-out, each in plan order.
  - On the demo brief (seed-42 world, 35 lines, ₹2 lakh):
    - no line takes more than 8.3% of the spend, the regions split 48/52 and the categories 35/65, so nothing is over-concentrated;
    - cannibalisation takes 86% (SKU0035 North), 82% (SKU0035 West) and 52% (SKU0006 West) of those lines' incremental profit, so 3 lines are flagged;
    - the highest line stock-out probability is 10.8%, so nothing is flagged.

    The planner agent therefore loops the demo at least once.
  - We rejected a per-SKU spend share, an HHI, a plan-level cannibalisation share and region stock-out probabilities (the latter grows with the number of lines a region has). We also rejected keeping the thresholds as constants or in `CompanyPolicy`: they are review settings, not rules a brief may only tighten.

## Findings and open issues

- **D3. `RiskFinding` joins `Violation` as an open issue, with no migration.**
  - The domain gains `RiskCode` (`OVER_CONCENTRATION`, `HEAVY_CANNIBALISATION`, `STOCKOUT_RISK`) and `RiskFinding`, with these fields: `kind="risk"`, `code`, `message`, `feedback`, `sku_id`, `region`, `category`, `actual` and `limit`.
  - `Violation` gains `kind="violation"` as a default, so rows stored before #48 still read.
  - `OpenIssue = Violation | RiskFinding` is the type of `PlanRevision.open_issues`, `PlanningState.critic_findings` and `SessionRecorder.save_open_issues`. It is stored in the same `plan_revisions.open_issues` JSONB column.
  - The API contract changes: `open_issues` is a list of `OpenIssue`. The frontend types were regenerated, and `openIssueSchema` is a discriminated union on `kind`.
  - This matches CONTEXT.md's "open issue": a violation or a risk finding.
  - We rejected a separate `risk_findings` column (a migration), adding risk codes to `ViolationCode` (which mixes hard constraints with risks), and keeping findings out of the revision.

## The loop

- **D4. Every violation and every risk finding loops back, except in these cases.** `critic.handoff` hands the plan to the Explainer when:
  - `plan_valid`: the attempt has no findings;
  - `infeasible`: the attempt carries a relaxation or is `INFEASIBLE`. Only an amended brief can apply the relaxation (AG-06, D10);
  - `default_sequence`: the default sequence planned the attempt (D6);
  - `cap_reached`: this is the fourth attempt.

  Otherwise it loops back. That is at most 3 loop-backs, so at most 4 planner attempts per planning round (`MAX_ATTEMPTS`).
  - **Amended by ADR 0059:** a fifth reason, `findings_repeated`, hands the plan on when an attempt's findings repeat the previous attempt's exactly. The recorded e2e and clarify sessions ran 4 identical attempts to the cap.
  - **This fixes SPEC §9.6's edge "violations and iteration < 3"**, which is now "findings and attempts < 4". `iteration` still counts every planner run in the session, and an amendment (#50) starts a new round with no attempts.
  - We rejected looping on violations only, which almost never fires: an optimised plan has none (ADR 0046 D11). We also rejected a second, "high" severity threshold.
- **D5. Feedback is one more message in a fresh planner conversation.**
  - `plan_with_tools(..., feedback=findings)` opens with the system prompt, the planning request and the brief, and then the Critic's findings as JSON: each issue's kind, code, message, feedback, SKU, region and numbers.
  - A restart (ADR 0027) keeps the feedback.
  - Planner prompt v2 tells the planner to plan again from the start and address each finding with its levers: narrow `generate_candidates` by SKU ids or mechanisms, tighten the optimiser options, or use `compare_mechanisms`. It may never loosen the brief (ADR 0049 D2).
  - The planner does not see its earlier tool calls. We rejected continuing the previous conversation (a bigger checkpoint and more tokens each attempt), and applying the feedback in the graph, which takes the decision from the planner (AG-03).
- **D6. The default sequence is not looped.**
  - When the graph has no planner agent, or the attempt is degraded (ADR 0049 D7), the Critic hands the plan on at once. The default sequence would plan the same revision again.
  - We rejected looping anyway, which costs up to 3 identical re-solves, about 30–45 s. We also rejected teaching the default sequence to act on feedback.
- **D7. The best attempt** has the fewest violations, then the fewest risk findings, then the highest objective; a tie goes to the later attempt (`critic.best_attempt`). Its findings are the revision's open issues. We rejected "always the last attempt" and "the highest objective without violations".
  - **Amended by ADR 0078:** fewer risk findings win only among the attempts within `CRITIC_OBJECTIVE_TOLERANCE` (5%) of the best plan-time objective.
- **D8. Attempts are drafts, and only the chosen plan becomes a plan revision.**
  - The Planner node appends a `PlanAttempt` (plan, plan facts, notes, degraded reason) to `PlanningState.attempts`. The Critic fills in its findings.
  - When the Critic hands on, it saves the best attempt as the plan revision, then its open issues. It also sets `plan`, `plan_facts`, `planner_notes`, `planner_degraded` and `critic_findings` in the state from that attempt.
  - **This amends ADR 0046 D5**, where the Planner saved the revision. Revision numbers and #50's diffs stay one per planning round.
  - Attempts are kept in the checkpoint and the trace, not in the read model. We rejected saving every attempt as a revision: approval takes only the latest revision (ADR 0046 D7), and #50's diffs would compare drafts.
- **D9. Each attempt has the planner's own limits**: 8 LLM steps and 16 tool calls (ADR 0049 D5).
  - Worst case, a round is 4 times ADR 0049's estimate: about ₹16 on `gpt-4.1-mini`, or about ₹88 if the `claude-sonnet-5` fallback answers every step.
  - **Cost note:** that fallback worst case exceeds SPEC §6's ₹20 per session. E9 measures the cost and E11 tunes it.
  - ADR 0059 leaves the worst case as it is, but a round whose findings repeat now stops after 2 attempts, not 4.
  - We rejected a shared budget of 16 steps and 32 tool calls, which would degrade later attempts.
- **D10. AG-06 keeps ADR 0044.**
  - `solve` already attaches the smallest relaxation and the binding constraints to an infeasible result, on both paths. The planner prompt still tells the agent to call `relax_constraints` on `INFEASIBLE`, as a what-if.
  - An infeasible attempt is not looped (D4), and the Explainer names its binding constraints and relaxation (ADR 0050).
  - Graph tests cover the default sequence, on the small world with an unreachable clearance target, and the agent path.
  - We rejected making the agent call `relax_constraints` itself, with a loop-back when it does not: that repeats the solver's work and costs an attempt.

## Trace

The Critic emits a `finding` trace event (ADR 0047) for each violation (source `plan_validation`) and each risk finding (source `risk_review`) of every attempt. It then emits one `decision` for its route: `loop_back`, or why it hands the plan on (`plan_valid`, `infeasible`, `default_sequence` or `cap_reached`). When there was more than one attempt, the handoff's summary names the attempt that goes on. #45's trace test now expects `default_sequence` where it expected `open_issues`: a default-sequence plan with violations is handed on for that reason.

## Consequences

- There are new public names:
  - domain: `RiskCode`, `RiskFinding` and `OpenIssue`;
  - guardrails: `review_risks` and `RiskThresholds`;
  - agents: `PlanAttempt`, `CriticFeedback`, `FindingFeedback`, `MAX_ATTEMPTS`, and `GraphTools.risk_thresholds`;
  - api: `Planning.risk_thresholds`;
  - `plan_with_tools` gains `feedback`.
- There are new settings: `CRITIC_LINE_SPEND_SHARE`, `CRITIC_GROUP_SPEND_SHARE`, `CRITIC_CANNIBALISATION_SHARE` and `CRITIC_STOCKOUT_PROBABILITY`.
- There is no migration. The OpenAPI contract and frontend types changed (`OpenIssue`, `RiskFinding`, `Violation.kind`).
- The prompts are critic v1 (new) and planner v2. No planner cassette was committed, so nothing committed is invalidated.
- **Cassettes to record** (#51; nothing was recorded here). For each committed brief, after `make data` and `make train`:
  - the planner agent's steps for each attempt, where every attempt after the first opens with the Critic's feedback message;
  - one Critic feedback call for each attempt that has risk findings. On the demo brief that is at least the first attempt (3 lines of heavy cannibalisation).

  `make record-cassettes` today records only the reading and one planner attempt. #51 extends it to the full graph.

  Until then, replay misses the Critic's call, so the template feedback stands, and misses the planner's, so it degrades and the default sequence is not looped. The demo therefore reaches Approval in one pass, with the demo's risk findings as open issues.
- Follow-ups:
  - #50 starts a new round (no attempts) on an amendment;
  - #51 records the full-graph cassettes;
  - E9 measures loop rates and cost;
  - E10 shows open issues with their feedback.
