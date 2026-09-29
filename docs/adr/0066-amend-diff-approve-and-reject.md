# The session page reviews the latest plan revision in one card that approves after a confirm, rejects with a reason and amends; the revision's diff shows in the plan, and an audit trail lists every amendment and decision

E10 (#64) is where managers stay in control (AG-05, SF-04).
- An amend box sends amendments.
- After one, a plan-revision diff shows the added, removed and changed lines, the objective delta and the change explanation.
- Approve and reject act on the shown plan revision, and a rejection needs a reason.
- An approved session is shown as final and read-only, with its audit trail.

The API already carries everything:
- `POST /amend` returns `202` with the session back in `planning` (ADR 0052 D2).
- `/approve` and `/reject` return `200` with the decided session (ADR 0046 D4).
- The latest revision holds its `diff` and `explanation.changes` (ADR 0052 D8–D9).
- The read model lists `amendments` and `decisions`.

SPEC, #12 and #64 leave open:
- where the controls and the diff sit;
- whether earlier revisions can be browsed;
- how approve is guarded and how a reason is validated;
- what a final session and its audit trail look like;
- how the page picks up the new revision;
- how conflicts show;
- the client's shape, which #62 and #63 reuse;
- which journeys prove it on which recorded sessions.

We chose these with the owner (D1–D12 on #64; every recommended option). D11 then had to move its approval onto another session, as it records.

## Decisions

- **D1. A "Review plan revision N" card follows the status card**, where the clarification form sits (ADR 0061 D1).
  - It holds approve, reject and the amend box, so the manager acts without scrolling past the plan.
  - It shows only while the session is `awaiting_approval` or `rejected`, the two statuses that accept a decision or an amendment (ADR 0046 D6, ADR 0052 D1).
  - It is keyed by the revision and the status, so a new revision or a decision starts it afresh.
  - We rejected putting it after the plan (SPEC §11's order), which means scrolling in the demo, and a sticky action bar.
- **D2. The diff is a "What changed from plan revision N" section in the plan card**, between the summary and the region tabs. It shows whenever the latest revision has a `diff`, so it survives a reload. `RevisionDiffView` shows:
  - the amendment that led here;
  - `explanation.changes`, with a "Template explanation" badge when the template wrote it;
  - the request changes, "Marketing budget: ₹8 lakh → ₹6 lakh", labelled by `fieldLabel`;
  - a "Plan totals" table: the objective and promo cost before, after and their signed change. The objective and its change name `run_optimizer`; the promo cost names `generate_candidates` (ADR 0060 D2);
  - an Added, a Removed and a Changed table. The first two show each line's decision, promo cost and expected incremental profit. Changed lists each changed field as before → after, with the decision numbers sourced;
  - "N plan lines unchanged.", or "No plan line changed." when no line was added, removed or changed.

  The diff is always against the previous revision, which is all the API stores (ADR 0052 D8). We rejected a separate card, and a "Changes" tab beside the regions that hides it behind a click.
- **D3. No revision history.** The page shows the latest revision and its diff. The audit trail (D6) names every revision that was amended or decided. The read model holds only the latest revision. Browsing earlier ones would need a new endpoint, and caching seen ones in the browser is lost on reload.
- **D4. Approving takes two clicks.**
  - "Approve plan revision N" asks "Approving makes plan revision N final: it can't be amended, approved or rejected afterwards." with "Confirm approval" and "Cancel".
  - An `INFEASIBLE` revision cannot be approved (ADR 0046 D10). Its button is disabled with "An infeasible plan can't be approved: amend the brief first." It can still be rejected or amended. The one-click relaxation is #62's.
  - We rejected a single click, which cannot be undone, and a modal, which needs a new component.
- **D5. A rejection needs a reason.**
  - "Reject plan revision N" opens a form asking "Why are you rejecting plan revision N?".
  - A blank or whitespace reason says "Give a reason for rejecting." and sends nothing.
  - The reason is capped at the API's 2000 characters and sent trimmed.
  - We rejected a minimum length above the API's, and an always-visible reason box.
- **D6. Final sessions and the audit trail come from the read model.** No backend change is needed.
  - An approved session's status card shows a "Final" badge and "This plan is final: it can no longer be amended, approved or rejected." The review card is gone.
  - An "Audit trail" card ends the main column once there is any amendment or decision. It merges `amendments` and `decisions` in time order, each with its time:
    - "Amended plan revision 1: “Budget cut to ₹6 lakh”", with a "Relaxation accepted" badge when it accepted one;
    - "Rejected plan revision 1: <reason>";
    - "Approved plan revision 3".

    This extends CONTEXT.md's audit trail, the decisions, with the amendments between them.
  - A rejected session keeps the rejection note in its status card, and its review card offers only the amend box.
  - We rejected putting the trail in the status card, and showing it only once approved.
- **D7. The response is shown at once.**
  - `SessionView` puts every action's session in the query cache, as clarify does (ADR 0061 D8).
  - After an amendment's `202`, the status is Planning… and the one-second poll (ADR 0021, ADR 0057 D2) runs until the new revision waits for a decision. The SSE stream never closed, so the timeline carries on.
  - Until the new revision is saved, the read model still holds the amended one (ADR 0052 D10). The plan card shows it under "Re-planning after your amendment “…”: showing plan revision N until the new one is ready."
  - `RegionPlanTabs` is keyed by the revision number, so a new revision opens on its first region; "Drop West" leaves no West tab selected.
  - After approval, the stream's `end` turns the timeline to Final.
  - We rejected invalidating and refetching, which waits for another request, and refetching on trace events.
- **D8. Errors show inline and keep what was typed.**
  - A failed action shows an alert on its card: "Couldn't approve plan revision N: <reason>", "Couldn't reject…" or "Couldn't amend the brief: …".
  - The reason is the API's `detail`: a 409's own sentence, the first validation message for a 422, the reason for a 404 or 503, or the network error.
  - On a 409 the session is also reloaded, so a session decided or amended elsewhere shows as it is.
  - The amendment and the rejection reason stay in their boxes. Clarify keeps its fixed 409 sentence (ADR 0061 D9).
  - While one action is being sent, every action on the card is disabled.
  - We rejected a fixed message per action, because a 409 has several causes that the API words well, and toasts.
- **D9. One client shape for every session action.**
  - `lib/api/sessions.ts` adds `amendSession(id, {text} | {acceptRelaxation: true})`, `approveSession(id, revisionNumber)` and `rejectSession(id, revisionNumber, reason)`.
  - They and `clarifySession` share `SessionActionResult` (`{ok: true, session} | {ok: false, reason, conflict}`) and one post helper.
  - `SessionActions` is `{clarify, amend, approve, reject}`, owned by `SessionView`. `SessionDetails` takes any subset of it.
  - `amend` takes `{acceptRelaxation: true}`, so #62's one-click relaxation calls `actions.amend({ acceptRelaxation: true })`. `AmendBox` stands alone for reuse.
  - We rejected a result type per call, and components calling the API themselves (ADR 0057 D8).
- **D10. The amend box is a labelled textarea**, "Amend the brief", with the placeholder "e.g. Budget cut to ₹6 lakh, or Drop West".
  - The text is required and not blank ("Write the change you want."), capped at 2000 characters and sent trimmed. "Amend and re-plan" is disabled while it sends, and the box clears once the amendment is accepted.
  - The textarea is hand-written in shadcn/ui's style (`components/ui/textarea.tsx`).
  - We rejected a single-line input, and suggestion chips taken from the recorded scripts.
- **D11. `amend.spec.ts` plays the recorded `demo` session's amendments** on the composed stack.
  - It reads the brief and both amendment texts from `backend/cassettes/sessions.json`, plans, amends with "Budget cut to ₹6 lakh", then with "Drop West".
  - After each round it checks the diff: the marketing-budget request change and the totals, then "Regions: North, West → North", the Removed table's West lines, and a tab list without West.
  - It checks that the audit trail lists both amendments, and, through the API, that revision 3 has the Explainer's recorded answer (`source: llm`).
  - **The demo cannot be approved through the API.** Every demo revision is `INFEASIBLE`, because the 60% namkeen clearance target is out of reach, and ADR 0046 D10 refuses to approve an infeasible revision. The recorder approved it by resuming the graph directly (`record_cassettes`), which skips the API's check. So the journey checks instead that approval is disabled with its note.
  - Approval moves to `approve.spec.ts` (D12). This amends the accepted D11 ("the full demo script, approve included") without a new recording.
  - Approving the demo from the UI needs its relaxation accepted first, which is one more recorded round. We leave that to #62, which owns the relaxation.
- **D12. Approve and reject each have a journey on the `e2e` session**, whose plan is `OPTIMAL`.
  - Neither decision makes an LLM call, so neither needs a cassette.
  - `approve.spec.ts` plans, confirms the approval, and sees "Approved" with "Final", no review card or amend box, and "Approved plan revision 1" on the audit trail. The API confirms the decision.
  - `reject.spec.ts` plans, sees a blank reason refused, then rejects with a reason. It sees "Rejected", the reason in the status card and on the audit trail, the amend box still offered and no approve or reject button. The API confirms the reason.
  - `tests/e2e/session-scripts.ts` holds the three journeys' shared steps: reading a script, planning a brief and reading the session.
  - This adds two replayed planning rounds to CI, plus the demo's three.
  - We rejected adding the steps to the brief-to-plan journey, which mixes journeys, and rejecting inside the demo journey, whose route the recorded manifest does not cover.

## Consequences

- New frontend modules:
  - `components/review-panel.tsx`: `ReviewPanel`, `Approve` and `Reject`;
  - `components/amend-box.tsx`: `AmendBox`, `SubmitAmendment` and `ActionOutcome`;
  - `components/revision-diff.tsx`: `RevisionDiffView`;
  - `components/audit-trail.tsx`: `AuditTrail`;
  - `components/ui/textarea.tsx`;
  - in `lib/api/sessions.ts`: `amendSession`, `approveSession`, `rejectSession`, `SessionActionResult`, `AmendInput`, and the `Amendment`, `RevisionDiff` and `LineChange` types.
- `SessionActions` gains `amend`, `approve` and `reject`, and `SessionDetails` takes a partial set.
- There is no API, backend or configuration change, and no new recording.
- Three Playwright journeys join brief-to-plan and clarify: amend (demo), approve and reject (e2e).
- The simulation controls of #63 must hide on an approved session, whose plan is final (ADR 0046 D16).
