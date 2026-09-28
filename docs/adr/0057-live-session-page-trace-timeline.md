# The session page streams its trace with the browser's EventSource, reopens a stream it gave up on with backoff and drops repeated event ids, and shows each node run with its steps beside the session

E10 (#59) makes the session page the manager's cockpit. It shows the agent at work as a live trace timeline, fed from the proxied SSE stream of ADR 0047 with `Last-Event-ID` resume, and it shows what planning cost. SPEC §11 places the timeline on the left. #59 asks that it reconnect after a network blip without duplicates, that each panel have loading, empty and error states, and that the layout work at 1280px and above.

SPEC, #12 and #59 do not say how the client connects and recovers, whether the stream replaces polling, where the cost figures come from, or how the timeline groups events. We chose these with the owner (D1–D11 on #59; every recommended option).

## Decisions

- **D1. The browser's own `EventSource`, with a reopen and an id check.**
  - On a network blip the browser reconnects by itself and sends `Last-Event-ID`, so the API resumes after the last event (ADR 0047 D8).
  - After an HTTP error, such as the proxy's 502 when the API is down, the browser closes the source for good. `useTraceStream` then opens a new one after 1, 2, 4, 8 and 16 s. Once a reopened stream is live, the backoff starts again from the beginning. After five failed reopens, the timeline says "Lost the trace stream." with a Retry button.
  - A new `EventSource` cannot send `Last-Event-ID`, so a reopened stream replays the trace from the start. Event ids are consecutive per session, so `mergeTraceEvent` drops any event whose id is not above the last one kept. No event is shown twice.
  - The stream closes on its `end` event, and when the page goes away.
  - The EventSource factory can be injected, so vitest drives a scripted fake.

  We rejected a `fetch` stream with a hand-written SSE parser, which sends `Last-Event-ID` on every reconnect but means owning the framing and a parser to test. We also rejected `@microsoft/fetch-event-source`, a new dependency.
- **D2. The 1 s session poll stays** (ADR 0021). The stream feeds only the timeline, and the actions that #61 and #64 add will invalidate the session query. We rejected refetching on each `node_finished`, and replacing polling with the stream, as more coupling for little gain.
- **D3. The usage meter reads the read model's `usage`**, the server's sum of the token-usage events (ADR 0047 D9–D10), including `unpriced_models`. Each LLM call still appears in the timeline with its own tokens and cost. We rejected summing the streamed events in the browser, which would be a second copy of the server's arithmetic.
- **D4. One entry per node run.**
  - A `node_started` opens a run. Its steps are the tool calls, decisions, findings, clarifications and token rows that follow for that node, and its `node_finished` closes it.
  - The heading shows the node's name, "attempt n" when the node runs again (the Critic loop, ADR 0051), the outcome (Running, Done, Paused at an interrupt, Failed with its error) and the duration.
  - Every run stays expanded.
  - We rejected collapsing finished runs to a summary line (one more interaction to build and test) and a flat list (it hides the loop).
- **D5. What each step shows.**
  - A tool call shows the tool, ok or its error code, and a native `<details>` with the pretty-printed arguments and result summary.
  - A decision shows its code as a badge and its summary sentence.
  - A finding shows its source and code as badges, then its message.
  - A clarification shows its questions as a list.
  - A token row reads "model · input in / output out · ₹cost", or "no price".
  - Each step's clock time shows on hover.
- **D6. Figures.** Tokens use en-IN grouping. Cost shows rupees first, with paise, and dollars second, to four decimals. Each figure is a `SourcedNumber` whose source is the "LLM usage meter", the sum of the session's token-usage trace events. An unpriced model is listed as "tokens only, no price set", and a session with no calls says "No LLM calls yet."
- **D7. Layout.**
  - Only the session page widens, from `max-w-6xl` to `max-w-screen-2xl`.
  - A two-column grid puts the timeline in a sticky left column of 320–380px that scrolls on its own, with the session in the main column.
  - The timeline follows new events only while the manager is scrolled to its bottom.
  - Its header shows the connection: Connecting…, Live, Reconnecting…, Final or Disconnected. The indicator uses `aria-live`, not the status role, which stays the session's.
- **D8. One thin container.**
  - `SessionView` reads the session and the stream and hands them to presentational components.
  - The trace renders while the session is still loading, and after a failed session read.
  - An unknown session shows only "Session not found", and its stream is closed.
  - `SessionDetails` stays the main column's component, which #60–#64 extend, and now holds the `UsageMeter`.
  - The page keys `SessionView` by session id, so another session starts with an empty trace.
- **D9. Tests.**
  - Vitest renders every event kind from fixtures and the meter's tokens and cost. It also checks that a blip and a reopen continue without duplicates, the backoff and Retry, `end`, and malformed events.
  - The composed-stack Playwright journey (brief → plan) also asserts that the timeline shows the Context and Planner runs, a tool call and the Critic's decision, and that the meter counts the replayed calls. No second planning run is added.
  - As in ADR 0047 D12, there is no composed-stack network-blip test.
- **D10. These decisions are recorded here**, since #60–#64 build on this layout and hook, and not only in the README.
- **D11. A malformed event is skipped with a `console.warn`.** The browser still advances its `lastEventId`, so a resume does not ask for the event again.

## Consequences

- New frontend modules:
  - `lib/api/trace.ts`: zod schemas that `satisfies` the generated `TraceEvent` types;
  - `lib/trace-stream.ts`: `useTraceStream`, `mergeTraceEvent` and `RECONNECT_DELAYS_MS`;
  - `components/trace-timeline.tsx` and `components/usage-meter.tsx`;
  - `formatTokens`, `formatUsd`, `formatDuration` and `formatClockTime` in `lib/format.ts`.
- No API, backend or configuration change.
- The timeline and usage meter are the base the other E10 session tickets (#60–#64) build on. The status card stays in `SessionDetails`.
