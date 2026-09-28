# An amendment resumes Approval into a Context re-read and a new planning round, whose plan revision stores a deterministic diff that the Explainer says in words

E8 (#50) lets a promotions manager change their mind mid-way (AG-05). `POST /api/sessions/{id}/amend {text}` keeps the amendment. The Context agent reads the request again and the Planner plans a new round. The new plan revision stores a structured diff against the previous one: plan lines added, removed and changed, and the objective delta. The Explainer then writes what changed and why. Rejected sessions accept amendments.

SPEC, #10 and #50 leave open:

- which statuses accept an amendment, and what the endpoint returns;
- how amendments are stored;
- how the Context agent reads them;
- whether an amendment may loosen the brief;
- how a manager accepts a relaxation (ADR 0044, handed on by ADR 0048 D13);
- the diff's shape and where it lives;
- how "what changed" is grounded;
- the route, what an amendment resets and how revisions are numbered;
- what happens to earlier decisions, and to a failed re-plan.

We chose these with the owner (D1–D12 on #50; every recommended option).

## The endpoint

- **D1. Only a session paused at Approval accepts an amendment.** That is `awaiting_approval` or `rejected`, the two statuses in which the graph waits at the Approval interrupt (ADR 0046 D9). Every other status is `409`: `planning`, `awaiting_clarification`, `approved` and `failed`. An unknown session is `404`, and a missing checkpointer is `503`.
  - A manager awaiting clarification writes any change into their answers, which the Context agent reads the same way.
  - We rejected amending at Clarify, which is a second resume path. We also rejected queueing an amendment while planning, which is racy and needs more state.
- **D2. `202`, and the graph resumes in the background**, as `/clarify` does (ADR 0048 D6).
  - The response is the `SessionResponse` with the session back in `planning` and the amendment in `amendments`. Planning a new round can take up to a minute.
  - `SessionStore.amend` moves the status with a conditional `UPDATE … WHERE status IN ('awaiting_approval', 'rejected') AND <latest revision> = n`, which also appends the amendment. The per-session lock covers amendments, answers and decisions, so two requests never resume one interrupt.
  - We rejected a synchronous `200` that returns the new revision, which blocks the request for as long as planning takes.
- **D3. The body is `{text}`**, as SPEC §10 has it, with no `revision_number`.
  - The text is 1–2000 characters and not blank. Unknown fields are `422`.
  - An amendment is relative ("cut budget to ₹6 lakh") and makes nothing final, so a stale tab is harmless. The store still records which revision it amended (D4).
  - We rejected `{text, revision_number}` with a `409` when the number is not the latest (ADR 0046 D7's rule for decisions): it departs from SPEC's body for little gain.

## Storage

- **D4. `Amendment` is a domain value**, stored as a JSONB list in `planning_sessions.amendments` (migration 0013), oldest first. It has:
  - `text`;
  - `amends_revision`, the latest revision when it was made;
  - `relaxation`, the relaxation it accepts (D7), or null;
  - `amended_at`, the server's `now()`.

  `SessionResponse` gains `amendments`. The graph's state keeps only their texts (`PlanningState.amendments`), which the Context agent reads. This mirrors how clarifications are stored (ADR 0048 D5).
  - We rejected an `amendments` table with a foreign key to the revision. It gives a relational audit trail like `approvals`, but needs more store code.
  - We rejected keeping amendments in the graph's state only, which leaves E10 nothing to show.

## Reading amendments

- **D5. The same single Context call reads the brief, the answers and every amendment**, oldest first, as quoted JSON after the brief. This is the path ADR 0048 D5 prepared, and the deterministic `interpret` is unchanged.
  - The rules for reading amendments are a separate prompt block, `prompts/context_amendments.md` (context amendments v1). It is added to the system prompt only when there are amendments, so a brief without them is sent exactly as before and the committed cassette's hash is unchanged. The rules are:
    - later amendments override earlier text, field by field;
    - `regions_phrase` and `categories_phrase` name the scope after the amendments ("North and West" amended with "drop West" is "North"). Without this rule the resolver would still read "drop West" as both regions (ADR 0048 D1);
    - a number an amendment states replaces the brief's.
  - A re-read that leaves a critical field open goes to Clarify as usual (ADR 0048), and the answer resumes into planning.
  - Each amendment round is one more Context call, so it needs its own cassette to replay (#51).
  - The planner agent's opening message still carries the brief without the amendments. The planning request is what it plans, and it may not loosen it (ADR 0049 D2). This keeps its first-round hashes unchanged.
  - We rejected a second "amendment delta" LLM call applied to the previous request. It edits more precisely, but needs a second schema, prompt and cassette, and duplicates the reading logic.
  - We rejected a deterministic parser for common forms ("cut budget to ₹X", "drop <region>"). It avoids the LLM there, but is brittle and makes two paths. #124's deterministic Context fallback (ADR 0053) reads amendment texts only when the LLM is down.
- **D6. An amendment may change any brief field, in either direction.** It may raise the budget, add a region or lower the minimum margin. Company policy still binds through `plan_limits`, and a value that would loosen it is flagged as an assumption (ADR 0007, ADR 0048 D7). We rejected tighten-only amendments, which block a legitimate "raise the budget".

## Accepting a relaxation

- **D7. `/amend {"accept_relaxation": true}` accepts the latest revision's relaxation** (ADR 0044). The body has exactly one of `text` or `accept_relaxation: true`; neither or both is `422`. A revision with no relaxation is `409`.
  - `agents.relaxation_amendment` writes the amendment's text from the relaxation, one clause per change, each value exact to the paisa or basis point: "Accept the smallest relaxation: lower the clearance target for SKU0029 to 70.27% sell-through; raise the marketing budget to ₹20,344.46." The `Relaxation` is stored with the amendment.
  - The Context agent reads it like any other amendment, so it composes with later ones. The LLM only lifts numbers the text states (ADR 0048 D11).
  - This settles ADR 0046 D10's "amend the brief with its relaxation first".
  - We rejected applying `optimizer.relaxed_request` deterministically and skipping Context (Approval → Planner). That gives exact values and needs no cassette, but makes two routes and leaves that round's assumptions stale.
  - We rejected leaving it to E10 to pre-fill the amend box, which makes acceptance UI-only.

## The diff

- **D8. `RevisionDiff` is stored on the new revision** as `PlanRevision.diff` (JSONB `plan_revisions.diff`, migration 0013). It is null for revision 1.
  - Plan lines are matched by (SKU, region), which a plan holds at most once (ADR 0004).
  - `added` and `removed` are the full revision lines, since the read model shows only the latest revision.
  - `changed` lists a line in both revisions whose **decision** differs: mechanism, depth, duration, start week, target segment or bundle partner. Each entry has its before and after lines and the names of the changed fields.
  - `unchanged` counts the lines with the same decision, even when their expected numbers moved, because other lines changed around them.
  - The diff also carries:
    - `objective_before`, `objective_after` and `objective_delta`, the last null unless both revisions have an objective;
    - `promo_cost_before`, `promo_cost_after` and `promo_cost_delta`;
    - `request_changes`: each planning-request field that changed, with its before and after values as display text ("₹10 lakh" → "₹6 lakh", "North, West" → "North").
  - `guardrails.diff_revisions` computes it, outside `promopilot.agents`, which may do no business arithmetic (ADR 0049 D10). `guardrails` already owns the formatters that the display text needs.
  - We rejected counting a line whose numbers shifted as changed, which is noisy.
  - We rejected storing only the (SKU, region) keys, which would lose removed lines from the read model.

## What changed and why

- **D9. The Explainer's single call also writes `changes`.**
  - `ExplainerAnswer` gains `changes`, and `PlanExplanation` gains `changes` (null for a revision that no amendment produced).
  - The LLM's view (`plan_data`) gains `changes_from_previous` when the revision has a diff. It holds:
    - the request changes, which are the "why";
    - the lines added, removed and changed, and the line counts;
    - the objective and promo cost before, after and change, every amount pre-formatted.
  - The amendment's own words are not in the view. ADR 0050 D3 keeps user text out, so a number typed into an amendment can never ground an explanation; the request changes carry the stated values instead.
  - When there is a diff, a blank or missing `changes` is an invalid answer, and `changes` is grounded like the summary. It is regenerated once, then the whole template stands (ADR 0050 D6).
  - The template writes `changes` from the diff alone: "Plan revision 2 changes plan revision 1. The planning request changed: the marketing budget from ₹10 lakh to ₹6 lakh. Removed: SKU0002 in West. … The objective goes from ₹3.7 lakh to ₹2.5 lakh (down ₹1.2 lakh), and the promo cost …". A hypothesis property checks that it always passes grounding against the view.
  - The Explainer prompt is explainer v2. No Explainer cassette is committed, so nothing committed is invalidated.
  - We rejected a second LLM call for changes only, which needs its own fallback and one more cassette per amendment.
  - We rejected template-only change sentences, which leave the LLM out of AG-05's "what changed and why".

## The graph

- **D10. The route is Approval → Context → Clarify or Planner. A new round starts, and its revision is the next number.**
  - `resume_with_amendment` resumes the Approval interrupt with an `AmendAnswer`, which joins the checkpoint allowlist.
  - The Approval node emits a `decision` trace event (`amended`, naming the revision and the text). It then:
    - appends the text to `amendments`;
    - clears `attempts`, `critic_findings`, `questions`, `planner_notes`, `planner_degraded`, `explanations` and `approval`.

    This is #48's "an amendment starts a new round with no attempts" (ADR 0051).
  - `plan` stays as the previous revision until the Critic saves the new round's.
  - The Critic's save point (ADR 0051 D8) numbers the chosen attempt `previous.number + 1` and attaches its diff from `plan`. The request changes are computed against `plan_request`, a new state field holding the request that `plan` was planned on. The first round's revision is number 1 with no diff.
  - `previous.number + 1` is allowlisted in the no-business-arithmetic test as revision bookkeeping, like `iteration + 1`.
  - `iteration` keeps counting every planner run in the session.
  - We rejected having the store assign `max + 1` on insert, which avoids the allowlist but must thread the number back into state.
- **D11. Earlier decisions stay as they are.** Rejections stay in `approvals`. A revision amended while awaiting approval gets no decision row; its amendment's `amends_revision` records that it was superseded. Earlier revisions stay in `plan_revisions`. Approve and reject still take only the latest revision (ADR 0046 D7). We rejected an implicit `superseded` decision, which widens `DecisionKind`, the API enum and the check constraint.
- **D12. A failure while re-planning fails the session**, as any planning failure does (ADR 0046 D14). A replayed stack with no cassette for the amendment's Context call does not fail, though: #124's fallback (ADR 0053) reads the brief and every amendment by rules, and asks about an amendment the rules cannot read. #51 records the cassette. We rejected restoring the previous status with the amendment marked failed, which keeps the session usable but needs new state and store paths.

## SPEC and earlier ADRs

- **SPEC §9.6's diagram** had "Approval → Planner: amend". It now draws Approval → Context: amend, since #10 and #50 have the Context agent read the request again first.
- **SPEC §9.6's state** listed `diff_from_previous`. The diff lives on the plan revision, and the state holds it as `plan.diff`.
- **AG-05's "at any point"** is limited to the Approval pauses (D1).
- **ADR 0046 D15 still applies.** An amended session that is re-planning when the API restarts fails. Its previous revision, which could have been approved, then no longer can be.
- **ADR 0049 D10's arithmetic test** gains an allowlist entry for `previous.number + 1`.
- **ADR 0051 D8's save point** also numbers the revision and attaches its diff.

## Consequences

- **Migration 0013** adds `planning_sessions.amendments` and `plan_revisions.diff`, both JSONB and null before #50.
- **New public names:**
  - domain: `Amendment`, `RevisionDiff`, `LineChange` and `RequestChange`;
  - guardrails: `diff_revisions` and `request_changes`;
  - agents: `AmendAnswer`, `resume_with_amendment`, `relaxation_amendment`, `plan_data` and `explainer_prompt`;
  - data: `SessionStore.amend` and `AMENDABLE`;
  - `PlanningState.plan_request`;
  - `PlanExplanation.changes`.
- **The API contract changes.** It gains `POST /amend`, `SessionResponse.amendments`, `PlanRevision.diff` and `PlanExplanation.changes`. The frontend types and zod schemas follow. The diff view, the amend box and accepting a relaxation are E10's.
- **Prompts:** context amendments v1 (new, sent only with amendments) and explainer v2.
- **No new configuration.**
- **Cassettes to record (#51; nothing was recorded here).** For each amendment of a recorded session:
  - the Context call with the amendment block;
  - the planner agent's attempts;
  - the Explainer call with `changes`.

  SPEC §12's Playwright journey (brief → plan → amend → approve) needs them.
- **Tests:**
  - graph tests: "cut budget to ₹6 lakh" plans within the new budget with a diff, and "Drop West" removes West's lines and lists them as removed. They use a pool planner on a North-and-West small world, plus the optimiser on the small world (₹20,000 cut to ₹6,000, then "drop South");
  - the change explanation passes grounding;
  - a rejected revision accepts an amendment;
  - a new round has one attempt;
  - an amendment that opens a critical field asks first;
  - with the LLM down, "cut budget to ₹6 lakh" is read by #124's rules and re-planned, with a `context_fallback` decision;
  - API contract tests for `/amend`, including `409` on approved, planning and clarification-waiting sessions and `422` bodies, plus accepting a relaxation and amending after a restart.
- **Follow-ups:**
  - #51 records the amendment cassettes;
  - E10 shows the diff, the amend box and an "accept the relaxation" button.
