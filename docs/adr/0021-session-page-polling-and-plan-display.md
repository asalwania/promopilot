# The session page polls every second, stops on any settled status or failed read, and shows plan numbers in en-IN rupees

E3 (#24) adds the manager's side of the walking skeleton: a brief composer on `/` and a session page at `/sessions/[id]` that polls `GET /api/sessions/{id}` through the same-origin proxy (ADR 0018) with TanStack Query. The E3 spec says to poll "until the session leaves `planning`" and to show "a clear error state". It does not fix the cadence, what happens when the read itself fails, or how numbers are displayed. We chose these with the owner:

- **Poll every 1 s while `planning`, and stop on every other status.** With replay cassettes a session plans in about a second. `awaiting_clarification`, `approved` and `rejected` cannot occur until E8, but they stop polling too, so a new status never spins.
- **A failed read stops polling and offers Retry.** TanStack retries a failing GET twice with its default backoff. After that, the page shows "Couldn't load the session" with the reason (`HTTP 502`, the network error or a contract break) and a Retry button. This also holds if the API drops while the page already shows `planning`: the error replaces the spinner. A `404` shows "Session not found" at once, with no retry and no button.
- **Only `planning` shows a spinner.** `failed` shows the session's `error` as an alert.
- **Plan numbers use en-IN rupees with no decimals** (`₹1,23,456`, negatives as `-₹13,813` in the destructive colour). Depth is shown as `20%`, duration as `4 wk`, weeks as `W105`, and mechanisms by name (`% off`). The table has the ticket's columns plus the start week. There is no totals row, because the UI does not add up numbers the tools did not compute. An empty revision says that no plan line fits within the marketing budget.
- **The composer is a textarea with "Plan it" only.** The button is disabled while the brief is blank or a request is in flight, and the textarea stops at 2000 characters and shows a counter (ADR 0020's limits; the API still validates). If the session cannot be created, the reason appears inline. The four example briefs and the constraint form (SPEC §11) wait for E10. The health panel stays on the home page.

## Consequences

- The session page reads through `getSession`, which throws a `SessionLoadError` (`notFound` for a 404). Components never see a raw `Response`.
- E8's SSE trace stream can replace polling in the same `SessionView` container. `SessionDetails` renders one `SessionResponse` and does not care how it arrived.
