# Every step of the agent graph is a numbered trace event in Postgres, streamed over SSE, and a session's cost is the sum of its token-usage events

E8 (#45) makes planning observable (SF-01). Every step of the agent graph becomes a typed **trace event**, and the events are persisted in order with ids. They stream over `GET /api/sessions/{id}/events` as SSE with `Last-Event-ID` resume, through the web proxy. Logs are structured JSON that carries the session id, and the read model gains per-session token usage and cost.

SPEC and #10 name the event kinds and the endpoint. They do not say how events are stored and numbered, how nodes emit them, what a tool call's summary holds, how the stream finds new events or when it ends, where cost comes from, or how much logging belongs here rather than in #71. We chose these with the owner (decisions 1–14 on #45; every recommended option).

## Events

- **1. Storage and ids.** Migration 0011 adds `trace_events(session_id, seq, node, kind, payload JSONB, created_at)` with primary key `(session_id, seq)`.
  - `seq` runs 1, 2, 3, ... within each session and is the event's SSE `id`, so "no gaps, no duplicates" is easy to check.
  - An append locks the session's row and writes `max(seq) + 1`, so even concurrent appends get consecutive numbers.
  - `kind` repeats the payload's kind for queries.

  We rejected a global `BIGSERIAL` id: ids jump between sessions, and a reader could skip an id whose transaction commits late. We also rejected UUIDv7 ids, which are opaque and hard to compare.
- **3. The kinds.** They are typed domain values (`promopilot.domain`), so data, agents and api share them. `TraceEvent` is `{id, session_id, at, node, payload}`, and `payload` is a union told apart by `kind`:

  | kind | payload |
  |---|---|
  | `node_started` | — |
  | `node_finished` | `outcome` (`completed`, `interrupted`, `failed`), `duration_ms`, `error` |
  | `tool_called` | `tool`, `arguments`, `ok`, `error_code`, `result_summary` |
  | `decision` | `decision` (a short code), `summary` (a sentence) |
  | `clarification` | `questions` |
  | `finding` | `source`, `code`, `message` |
  | `token_usage` | `model`, `input_tokens`, `output_tokens`, `cost_usd`, `cost_inr` |

  The `interrupted` outcome shows where a thread paused. LangGraph re-runs an interrupted node from its start when it resumes, so Approval appears as started and interrupted, then started again. The `failed` outcome carries the error, so the trace shows the failing node while ADR 0046's D14 (a node's error fails the session) stands as it is.

  We rejected a `node_finished` that exists only on success: a timeline could then not show a pause or a failure.
- **5. Tool-call summaries.** `result_summary` is a generic outline:
  - scalars are kept;
  - a list becomes `"<n items>"`;
  - objects are kept two levels deep and become `"<object with n fields>"` below that;
  - the whole is cut to 2,048 characters of JSON.

  Arguments are kept whole under the same cap. A tool error's summary is its message and details. We rejected cutting the JSON at N characters (it splits values), and a `summarize()` written for each of the 11 tools.

## Emitting

- **2. One call from anywhere in a node.** `GraphTools` gains `trace: TraceSink`. It defaults to `NoTrace`, so a graph built without one still runs. `build_graph` adds every node through `traced_node`, which does two things:
  - it emits the node's start and end;
  - while the node runs, it binds the session and node name in a context variable.

  Code inside a node then records anything with `await emit(payload)` from `promopilot.agents`. Outside a traced node, `emit` drops the event, as `record_usage` does (ADR 0027). New nodes (#46's Clarify) must be added through `build_graph`'s `add` so that they are traced too.

  We rejected two alternatives:
  - `tools.trace.emit(session_id, node, event)` in every node, which threads the session and node through every helper;
  - SPEC §9.6's `trace[]` in `PlanningState`. That would publish events only at step boundaries, so nothing would appear while a node runs, and every checkpoint would grow with the whole trace.

  **This amends SPEC §9.6.** The state has no `trace[]`; the `trace_events` table is the trace's only source of truth.
- **4. What this slice emits.**
  - Every node's start and end.
  - One `token_usage` event per billed LLM call. `build_graph` wraps its LLM in `TracedProvider`, which opens a nested `track_usage()` scope per call, so a billed refusal and each provider tried on a fallback count too.
  - A `finding` per Critic violation (`plan_validation`), then the Critic's `decision` (`plan_valid` or `open_issues`).
  - Approval's `decision` (`approved`, or `rejected` with the reason).
  - The LLM planner's (ADR 0049) tool calls: it calls its tools through `TracedToolRegistry`, which emits a `tool_called` event on every call, including a call that raises (error code `exception`) before the planner retries it.
  - The planner's own decisions as `decision` events: a refused call, a restart, a step or tool-call limit, a vanished plan, and falling back to the default sequence (`planner_degraded`).
  - The Explainer's fallback to the template (ADR 0050) as a `decision` (`explainer_fallback`, with the reason).

  The default sequence's internal steps are not dressed up as tool calls: they are the degraded path, and the planner's decision says it ran. `clarification` is emitted by the Context agent's Clarify (#46).

## Cost

- **9. Priced at emission, summed from the events.** Each `token_usage` event carries its cost, priced when the call is made with `LLM_PRICES` and `USD_INR_RATE` (ADR 0027) through `UsageMeter.totals`. `GraphTools.pricing` holds the prices. A model with no price keeps its tokens and has a null cost.

  The session's `usage` in the read model sums its `token_usage` events in order, including `unpriced_models`. So the events add up to the totals by construction, the totals survive restarts and decision requests, and a recorded cost is never repriced.

  We rejected two alternatives:
  - storing tokens only and pricing at read time, where a price change would rewrite the cost of past sessions;
  - running-total columns on the session, which are a second source of truth.
- **10. The read model.** `SessionResponse.usage` is `{calls, input_tokens, output_tokens, cost_usd, cost_inr, unpriced_models}`. It is always present, with zeros for a session with no LLM calls, such as one planned before E8. Events are served only over SSE; a JSON list endpoint is not in SPEC §10, and SSE from the start replays everything.

## The stream

- **6. FastAPI's own SSE.** The route uses FastAPI's own `EventSourceResponse` and `ServerSentEvent` (FastAPI 0.141). It sends a `: ping` keepalive comment every 15 s and sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`. The OpenAPI document gives each event's data the schema `TraceEvent | TraceStreamEnd`, so `make api-types` generates their types. We rejected `sse-starlette` (a new dependency that duplicates FastAPI) and a hand-written `StreamingResponse` (we would own the framing and the keepalive).
- **7. Polling, and when it ends.** The stream first sends every event after `Last-Event-ID`. Then it reads the table every `TRACE_POLL_INTERVAL_S` seconds (default 0.5). Each read takes the session's status first, then its events.
  - **Final** means `failed`, or `approved` with a graph that has run to the end (its last checkpoint has nothing left to run). Approval records the decision before its node ends and Done runs, so an approved status alone is not enough.
  - A session planned before E8 has no graph thread and is also final.
  - Once the session is final, one more read collects any events the last read missed. The stream then sends `event: end` with `{session_id, status}` and closes. The end event has no id, and the E10 client calls `close()` on it instead of letting `EventSource` reconnect.
  - A paused session (`awaiting_approval`, `rejected`, later `awaiting_clarification`) keeps its stream open.

  We rejected closing the stream at every pause and relying on the browser's reconnect, which reconnects over and over through long pauses. We also rejected an in-process `asyncio` notify, which is more code for a single-worker demo and does not reach across processes.
- **8. Resume.** `Last-Event-ID` is the only resume point. A missing or non-numeric value replays from the start, and an unknown session is `404` before the stream opens. We rejected an `?after=` query parameter (a second way to do the same thing) and `400` for a non-numeric id (browsers never send one).
- **11. Event names.** Trace events go out as the default `message` event, with their kind inside the JSON, so a client needs one `onmessage`. Only the closing event is named (`end`). We rejected `event: <kind>` on every event, which needs a listener per kind.

## The web proxy

- **12. Unbuffered through Next.** The proxy (ADR 0018) already streams bodies and forwards request headers, including `Last-Event-ID`, and the browser's abort signal. For a `text/event-stream` response it now also sets `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`. `next start` compresses responses with the `compression` middleware, which would hold events back until a compressed block fills; it skips a response marked `no-transform`.

  This adds to **ADR 0018's consequences**: the proxy changes headers for event streams, and only for them. We rejected `compress: false`, which turns gzip off for every response, and a composed-stack Playwright check of the stream, which is slow in CI. Unit tests cover the headers, chunk-by-chunk forwarding, `Last-Event-ID` and abort.

## Logs

- **13. JSON lines that name the session.** `promopilot.logs.configure_logging`, called by `build_app`, writes one JSON object per line (level, ISO time, event, fields). `LOG_FORMAT=console` gives readable text for development. `merge_contextvars` adds bound values to every line:
  - a session's background run and each decision request bind `session_id`;
  - `traced_node` binds `session_id` and `node`, so a line logged inside a node, such as `llm_retry`, says where it came from.

  Request ids, redacting secrets and logging briefs only at debug level remain #71's. Uvicorn's own access logs are not changed. We rejected binding the session id without configuring JSON output (the logs would not be structured yet) and doing all of #71 now.

## Testing

- **14. Billed fakes on the test side.** Token usage is tested with `tests/unit/agents/billed.py`'s `BilledProvider`, which wraps `FakeProvider` and reports a scripted `Usage` per call. `FakeProvider` itself is unchanged. No test calls a real LLM.
- The API tests check the ticket's criteria:
  - the stream emits every event in order with consecutive ids, then `end`;
  - resuming after ids 1, 4, n − 1 and n returns exactly the rest;
  - token-usage events add up to the session's usage.
- A live test serves the app over real HTTP and reads events while the session is still planning, because httpx's ASGI transport buffers whole responses.

## Consequences

- New public names:
  - domain: `TraceEvent`, `TracePayload`, the seven payload types, `NodeOutcome` and `SessionUsage`;
  - agents: `TraceSink`, `NoTrace`, `MemoryTrace`, `emit`, `traced_node`, `TracedProvider`, `TracedToolRegistry`, `LLMPricing` and `summarize`;
  - data: `TraceStore` and `TraceRead`;
  - api: `TraceStreamEnd`;
  - `promopilot.logs.configure_logging`.
- `SessionService` takes the trace reader and the poll interval.
- `agents/trace.py` is exempt from the no-business-arithmetic test (ADR 0049). Its only arithmetic is bookkeeping: numbering events in `MemoryTrace`, measuring node durations and cutting summaries short. Every cost comes from the LLM layer's `UsageMeter`.
- New settings: `TRACE_POLL_INTERVAL_S` and `LOG_FORMAT` (`.env.example`).
- `PlanningSession` and `SessionResponse` gain `usage`; the E3 page's schema follows the regenerated types.
- The trace timeline, its token and cost counters, and the client that closes on `end` are E10's.
