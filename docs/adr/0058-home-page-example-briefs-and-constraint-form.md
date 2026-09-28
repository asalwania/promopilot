# The home page offers four recorded example briefs, and its optional constraint form adds sentences to the brief rather than changing the API

E10 (#65) turns the home page into the brief composer that SPEC §11 describes. It has 4 example briefs, an optional constraint form (budget, minimum margin, regions, categories, window, clearance target) and a "Plan it" button. The example briefs must replay with no key: every example brief has a cassette.

SPEC, #12 and #65 leave open:

- which examples to show, and how the frontend keeps them equal to the recorded briefs;
- how the form's constraints reach the API, which takes `{brief}` only (SPEC §10);
- which fields the form offers, and how they are validated;
- what clicking an example does.

We chose these with the owner (D1–D11 on #65; every recommended option).

## Decisions

- **D1. Four examples, one per recorded session** in `backend/cassettes/sessions.json` (ADR 0054):
  - `demo`, the SPEC §3.2 brief. Its card suggests the recorded amendments, "Budget cut to ₹6 lakh" and "Drop West".
  - `e2e`, the quick ₹2 lakh Diwali push.
  - `clarify`, the brief with no budget. Its card suggests the recorded answer, "₹2 lakh".
  - `regional`, a new script: *"Plan a Christmas promotion for Snacks and Beverages across all regions. Marketing budget ₹5 lakh, with no more than ₹1 lakh in South. Stay within 3% of competitor prices on KVIs. Target young urban shoppers."* It shows what the other three do not: a regional budget cap, the KVI price tolerance, a second holiday and all four regions.

  It is planned only (no steps). Its recording needs a live key and the owner's OK, so it is recorded onto the branch before merge (`make record-cassettes ONLY=regional`). As with ADR 0054 D10, the committed-cassette test, the frontend's example guard and the images job's `--check` are red until then.

  We rejected an infeasible brief: ADR 0054 D1 left it to E9/E11 for the risk that the planner degrades. We rejected showing only the three recorded briefs, which falls short of SPEC §11.
- **D2. The examples are a frontend copy, and a test keeps the copy exact.** The web image is built from `frontend/` alone, so it cannot read `backend/cassettes/`. `frontend/src/lib/example-briefs.ts` holds each example's session name, title, description, brief and hint. `tests/unit/example-briefs.test.ts` reads `sessions.json` and `manifest.json` and fails if an example's brief is not its script's brief, or not recorded, word for word.
- **D3. Constraints become sentences after the brief; the API is unchanged.**
  - Each constraint set adds one sentence after `Constraints:`, e.g. `Marketing budget ₹8 lakh. Keep margin above 18%. Regions: North and West. Categories: Snacks and Beverages. Run it for Diwali. Clear at least 60% of 400g namkeen stock.`
  - The wording is chosen so that both the Context agent's LLM reading and its rules fallback read it. The fallback needs a rupee sign and "lakh", a percentage next to its cue word, exact region, category and holiday names, and a clearance sentence that names a product (ADR 0053 D3–D5).
  - The composer shows "PromoPilot will read" with the exact text, and counts its characters against the brief limit (2000).
  - Amendments, clarifications and the audit trail work unchanged, because the brief holds everything.
  - When the brief and the form disagree, the reader settles it as it settles any brief: two budgets are asked about. Regions and categories are merged by the rules fallback. The assumptions panel shows the result.
  - We rejected a structured `{brief, constraints}` API that overrides the reading. It is more exact, but it needs schema, store, Context and amendment changes, and a migration.
- **D4. The fields.** All are optional.
  - Marketing budget, in ₹ lakh.
  - Minimum margin, in %.
  - Regions and categories, as checkboxes. The categories are a static list, like the Region enum: the synthetic world's categories do not change.
  - The promo window, as one of the calendar's holidays (Diwali, Christmas, New Year, Holi, Eid), which both readers map to its weeks. Managers do not know week ids, and mapping dates would copy the calendar into the frontend.
  - A clearance target, as a product phrase and a sell-through %. A SKU id is not sent: the rules fallback reads a SKU id as the scope, not as a clearance target.
- **D5. Validation.** A zod schema checks the form when "Plan it" is clicked, with one inline message per field:
  - the budget must be above ₹0 and at most ₹1000 lakh;
  - the margin must be from 0% to 60%;
  - the sell-through must be from 1% to 100%;
  - a clearance target needs both the product (at most 80 characters) and the %.

  Editing a field clears its message. The brief is still required. "Plan it" is disabled while the composed text is over 2000 characters. Company policy (the margin floor, KVI tolerance) stays on the server, which reports a policy finding.
- **D6. Clicking an example replaces the brief and clears the form.** It does not plan. The text sent is then exactly the recorded brief, and the manager still clicks "Plan it".
- **D7. A started session opens `/sessions/{id}`**, as before.
- **D8. The form says what replays.** A note under it reads: "Constraints are added to your brief. Without an API key, only the example briefs replay exactly; other briefs still plan, with rule-based reading."
- **D9. The form uses shadcn/ui** `input`, `label` and `checkbox`, as generated and then formatted. The holiday picker is a native `select`, which is accessible and testable without a portal.
- **D10. No new Playwright journey.** The AC is Vitest. The E3 journey keeps typing the `e2e` brief, and #72's demo journey will click the examples.

## Consequences

- New frontend modules: `lib/example-briefs.ts`, `lib/brief-constraints.ts` (`validateConstraints`, `composeBrief`), `components/example-briefs.tsx` and `components/constraint-form.tsx`.
- `backend/cassettes/sessions.json` gains the `regional` script. A full re-record (for example after a prompt change) records it with the others.
- There is no API contract change, no migration and no new configuration.
- Using the form changes the brief, so on the key-free stack such a session misses its cassettes. It still plans, degraded: fallback reading, default planner sequence, template explanation (ADR 0049, ADR 0050, ADR 0053).
