# Walking-skeleton sessions: rupee budgets, a week table for the LLM, a naive planner with no uplift

E3 (#23) runs brief → planning request → naive plan → plan revision 1 over `POST`/`GET /api/sessions`. The E3 spec and SPEC leave several details open. We chose these with the owner:

- **The marketing budget is in rupees, as a float.** The E3 spec says "paise", but ADR 0015 (decided later, in E2) makes money float rupees everywhere except inside CP-SAT. ADR 0015 wins, so the planning request and every plan-line number are in rupees.
- **The LLM picks the promo window from a week table.** The context prompt lists the 26 weeks after the as-of week, with week id, start date and holidays by region, and the LLM returns start and end week ids from it. The LLM therefore never converts dates or computes weeks. Deterministic code then checks that the weeks are in the table, the window is ordered, and it starts strictly after the as-of week. It also checks that every region and category exists in the data. The brief reaches the LLM as a JSON string in the user message, never inside the system prompt.
- **A missing critical field fails the session.** Every field of the LLM's reading is nullable. If the brief states no marketing budget, regions, categories or promo window, the session becomes `failed`, and its error names the missing field. The agent never guesses. E8 turns this into a clarification. *(Replaced: ADR 0048 asks through the Clarify interrupt instead.)*
- **The naive planner has no uplift model.** Each in-scope (SKU, region) gets one option: PCT_OFF at 20%, All customers, starting at the window start, lasting min(window length, 4) weeks. Expected units are the average weekly units by segment over the 8 weeks before the as-of week. Options are ranked by base margin and added greedily while total promo cost stays within budget; an option that does not fit is skipped. With no uplift, each line's expected incremental profit equals minus its promo cost. We rejected a placeholder uplift factor because it would be an invented number shown as a forecast. E4 and E6 replace this planner.
- **Background tasks, and a restart fails what they left.** A session is planned by an `asyncio` task in the API process, so `POST` returns 202 at once. At startup, sessions still `planning` are marked `failed` ("interrupted by an API restart"), so the UI never spins forever. E8's checkpointer can later resume them instead.
- **Briefs are 1–2000 characters, not blank**; anything else is a 422.
- **App-state tables have no foreign keys into the data tables.** Reloading data (`TRUNCATE … CASCADE`) must never delete a session. The API also runs migrations at startup (best effort, since `/health` stays a liveness endpoint), so the session tables exist even before `make data`.

## Consequences

- The naive plan always shows a negative expected incremental profit. The skeleton proves the wiring, not the economics.
- The context prompt (`agents/prompts/context.md`) and the week table are part of the request hash (ADR 0019), so a calendar change or prompt edit needs `make record-cassettes`.
- All six session statuses exist from E3. Only `planning`, `awaiting_approval` and `failed` are reachable until E8.
