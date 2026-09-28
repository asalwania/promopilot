# The session page lists every assumption and highlights readings below 0.9 confidence, flagged values and rule readings, and asks open questions as a form whose answers resume planning at once

E10 (#61) shows the manager what the agent assumed and lets them answer its questions. SPEC §11 puts an assumptions panel with confidence in the session page's main column. #61 asks that low-confidence and clamped items stand out, and that a session awaiting clarification ask its questions as a form answered in place, after which planning resumes. The read model already carries everything: `assumptions` (ADR 0048 D4, with `fallback` from ADR 0053 D7), the open `questions` and the `clarifications` answered so far. `POST /clarify` returns `202` with the session back in `planning`.

SPEC, #12 and #61 leave open:

- where the panel sits;
- what counts as low confidence;
- how assumptions, flags and the fallback show;
- how questions render and are validated;
- what happens after the answers are sent, and on an error;
- a question asked again;
- how the page's actions reach the presentational components;
- tests.

We chose these with the owner (D1–D14 on #61; every recommended option).

## Decisions

- **D1. The panel sits in the main column**, after the status card, the clarification form and the usage meter, and before the plan. It replaces the E3 "Planning request" card: every request field is already an assumption (ADR 0048 D3), so the card only repeated four of them. We rejected keeping both, which shows the same values twice at 1280px, and putting the panel inside the status card.
- **D2. Low confidence is below 0.9** (`LOW_CONFIDENCE_BELOW` in `lib/assumptions.ts`).
  - No assumption scores below 0.7, because the Context agent asks instead (AG-02). A reading by rules scores exactly 0.7 (ADR 0053 D6). So AG-02's threshold would never highlight anything.
  - 0.9 catches readings by rules and weak fuzzy matches, but not near-exact ones.
  - We rejected below 1.0, which flags every near-exact match, and at or below 0.7, which flags only readings by rules.
- **D3. One compact table, in the Context agent's order.**
  - Its columns are field (a human label, or the raw name for a field the UI does not know), value, source ("From brief", "From data" or "Default") and confidence.
  - The confidence is a percentage and a `SourcedNumber` whose source is the Context agent, with how that score is made.
  - A row that needs attention is tinted and carries a text badge. Its note shows beneath its value.
  - The header says how many need a look.
  - We rejected pinning those rows to the top, which breaks the request's order, and grouping by source.
- **D4. Flagged items get one "Flagged" badge and their note.** For a policy clamp the note is the policy finding's message (ADR 0048 D7). We rejected a separate "Policy clamp" badge matched against the revision's `policy_findings`: a session awaiting clarification has no revision yet.
- **D5. The fallback shows twice.** A one-line note on the panel says "The language model was unavailable: these were read by rules." Each such row has a "Read by rules" badge. We rejected showing only one of the two.
- **D6. The panel always renders.** With no assumptions yet it says "The Context agent is reading the brief…" while planning, and "No assumptions were recorded." otherwise.
- **D7. Each question is a labelled single-line answer box.**
  - Its label is the question. It has a reason badge (Missing, Low confidence or Ambiguous) and suggestion buttons that replace the answer with the suggestion. The answer stays editable.
  - Every answer is required, and none may be blank; an unanswered box says "Answer this question." Each is capped at the API's 2000 characters.
  - One button, "Answer and resume planning", sends every answer, trimmed, as the API needs. It is disabled while the post is pending.
  - We rejected suggestions that append to the answer, and a textarea per question: answers are short.
- **D8. The 202's session is shown at once.** `SessionView` puts it in the query cache. The status becomes "Planning…", the form goes, and the one-second poll (ADR 0021, ADR 0057 D2) starts again until the plan or the next question. The trace stream never closed, so the timeline carries on. We rejected invalidating and refetching, which waits for a second request.
- **D9. Errors keep the answers.**
  - A `409` says "These questions were already answered." and the session is reloaded.
  - A `422` shows the API's message: its string `detail`, or the first validation message.
  - A `404`, a `503` or a network error shows its reason.
  - The manager can send again.
- **D10. The form is keyed by round** (`clarifications.length`), so a question asked again starts empty. It shows "You answered: “…”" beneath it (ADR 0053 D8 asks again, quoting an answer the rules cannot read). We rejected prefilling the earlier answer.
- **D11. Past answers are not listed.** The assumptions read again with the answers already show them, and D10 covers a repeat.
- **D12. Actions reach the page through one prop.**
  - `SessionDetails` takes an optional `actions: SessionActions`, only `{ clarify }` for now. `SessionView` owns the calls.
  - #64's amend, approve and reject join it.
  - Without it, the form says the answers cannot be sent.
  - We rejected the form calling `useQueryClient` itself, which breaks ADR 0057 D8's thin container.
- **D13. A second Playwright journey**, `tests/e2e/clarify.spec.ts`, plays the recorded `clarify` session on the composed stack.
  - It reads the brief and answers from `backend/cassettes/sessions.json` and types the brief.
  - It then sees the status "Awaiting clarification", one answer box per recorded answer, and the assumptions read so far.
  - It fills the recorded answers, sends them, and waits for the plan and "Awaiting approval".
  - Finally, it checks that the marketing budget became an assumption.
  - This adds one planning run to CI. We rejected clicking the home page's example card (ADR 0058), which couples this journey to that page, and extending the brief-to-plan journey.
- **D14. Tests.**
  - Vitest renders the panel from fixtures: sources, a low-confidence reading, a clamp with its note, the fallback note and badges, and the empty states.
  - It drives the form: the questions and reasons, a suggestion, blank answers blocked, the answers sent by id, the pending button, a refused answer and a repeated question.
  - It checks `clarifySession`'s status mapping.
  - It checks that `SessionView` goes from answering to the plan, and reloads on a conflict.

## Consequences

- New frontend modules:
  - `components/assumptions-panel.tsx`;
  - `components/clarification-form.tsx`;
  - `lib/assumptions.ts`, with `LOW_CONFIDENCE_BELOW`, `isLowConfidence`, `needsAttention` and `fieldLabel`;
  - `clarifySession` and `ClarifyResult` in `lib/api/sessions.ts`.
- `SessionDetails` gains `actions`. `PlanningRequestSummary` and the E3 question list are removed.
- There is no API, backend or configuration change.
- A field the Context agent adds later shows by its raw name until `fieldLabel` learns it.
