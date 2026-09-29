# Every API error answers `{detail, code, reference_id}`; inputs are capped in the request types and the body; LLM attempts, tool calls and background graph runs time out from config

E11's #69 asks that nothing breaks badly (SPEC §6 Security, spec #13). Every API error should use one schema with a code, a message and a reference id. Inputs should have maximum lengths in the API that the UI mirrors. LLM calls, tools and sessions should time out from config, and a timed-out session should end `failed` with a reason and a trace event.

Before #69 the API answered in three shapes:

- FastAPI's `{"detail": "<sentence>"}` for a raised `HTTPException`;
- `{"detail": [{type, loc, msg, input, ctx, url}]}` for a validation error, echoing the rejected input (a 1 MB brief came straight back);
- a plain-text 500 for anything unexpected.

No response had a request id. There was no cap on the body, the number of clarification answers or query strings. An LLM call waited up to the SDKs' 600 s default, and tools and graph runs could wait forever. We chose the following with the owner on #69, taking every recommended option except the session timeout's default, which is 900 s rather than 300 s: the live eval recording saw sessions take 125–870 s on a loaded machine, and #73 tunes it.

## Decisions

- **D1. The body keeps `detail` and adds fields.**
  - Every error is `ErrorResponse`: `{detail, code, reference_id, errors}`.
    - `detail` is the sentence to show the user, as it always was.
    - `errors` lists a 422's problems as `{loc, message}`; it is `null` on every other status.
  - Every existing reader of `detail`, and the API tests that check it, keep working.
  - We rejected RFC 9457 `application/problem+json`, a superset whose extra fields nothing reads, and `{error: {code, message, ...}}`, which would break every reader.
- **D2. The shape is set in one place: `promopilot.api.errors.install_error_handling`.**
  - Routers keep raising `HTTPException`. Handlers turn it, a request validation error, an oversized body and any unexpected exception into `ErrorResponse`, so a router added later needs no change. #57's evals router got the schema that way.
  - `create_app` installs it, and it also rewrites the OpenAPI contract:
    - every 4xx and 5xx response of every operation references `ErrorResponse`;
    - every operation that takes a body documents `413`;
    - FastAPI's `HTTPValidationError` and `ValidationError` schemas are gone.
  - We rejected typed domain exceptions in place of every `HTTPException`: they would touch every router and conflict with the parallel tickets.
- **D3. The code follows the HTTP status.**

  | Status | Code | Notes |
  |---|---|---|
  | 404 | `not_found` | |
  | 409 | `conflict` | The spec's "invalid transition"; a 409 also means a retrain is running or no data is loaded |
  | 413 | `payload_too_large` | |
  | 422 | `validation_failed` | |
  | 429 | `rate_limited` | Reserved for #70 |
  | 500 | `internal_error` | |
  | 502 | `api_unreachable` | The web proxy's |
  | 503 | `unavailable` | |
  | 504 | `timeout` | |

  - Any other 4xx, such as 400 or 405, is `bad_request`, and any other 5xx is `internal_error`.
  - `ErrorCode` is an enum in the contract, so #72 can add a code for "not in demo recordings".
  - We rejected a code per cause (`revision_not_latest`, `plan_final`, ...). Nothing branches on the cause today, and the sentence already names it.
- **D4. The reference id is the request's id.**
  - `RequestGuard`, a pure ASGI middleware, gives every HTTP request a uuid4. It stores it in `request.state.request_id` and sends it on every response as `X-Request-ID`, successes included.
  - `reference_id` is that id. A 500 logs the exception as `api.unexpected_error` with it, and the body says only "Something went wrong on our side. Quote reference <id> to report it.": never the exception's text or a traceback.
  - The API ignores a client's own `X-Request-ID`. #71 binds the id into every log line.
- **D5. A 422 reads as one sentence.**
  - `detail` is the first problem, made readable:
    - its field path without the `body`/`query`/`path` prefix;
    - a colon;
    - pydantic's message without the "Value error, " prefix.

    For example, `brief: String should have at most 2000 characters`, or the message alone for a rule on the whole body ("give either the amendment's text or accept_relaxation: true").
  - `errors` lists every problem with its full location, such as `body.brief` or `path.session_id`. Neither echoes the input. A location part longer than 64 characters, which can only be a client's dict key, is cut short.
  - Malformed JSON and the domain 422s (clarify answers that do not match the questions, an unknown category) get the same code.
- **D6. Limits.**
  - **Field lengths.** Brief, amendment, rejection reason and each clarification answer stay at 1–2000 characters (ADRs 0020, 0046, 0048 and 0052).
  - **New caps.**
    - A clarify request takes at most 20 answers, with question ids of at most 64 characters.
    - `category` query strings and the relations SKU path take at most 64 characters.
    - `n_runs` stays 100–5000 and `match_probability` 0–1.
  - **In the types.** The limits live in the request types, so the contract carries them as `maxLength`, `maxProperties`, `propertyNames` and `additionalProperties.maxLength`. The answer length moved from a validator into the type, so its message is now pydantic's.
  - **Body size.** `MAX_REQUEST_BODY_BYTES` (default 256 KiB, at least 1024) caps a POST, PUT or PATCH body.
    - The guard answers 413 at once when `Content-Length` says the body is larger, or when a chunked body passes the cap. Either way the app never reads it.
    - A body within the cap is read once and replayed to the app.
    - 256 KiB fits 20 answers of 2000 characters, even with every character escaped to 6 bytes of JSON.
  - **The UI mirror.** The UI takes its limits from one module, `frontend/src/lib/input-limits.ts`, and a Vitest test fails if they drift from `docs/openapi.json`.
  - We rejected env-configurable lengths served by a `GET /api/limits`: one more endpoint and a loading state, for values that do not change.
- **D7. Timeouts.** A layer that has one fails into what the layer above already handles.

  | Layer | Setting | Default | On timeout |
  |---|---|---|---|
  | LLM attempt | `LLM_TIMEOUT_SECONDS` | `60` | `TransientLLMError`, retried, then the fallback provider |
  | Tool call | `TOOL_TIMEOUT_SECONDS` | `120` | A `timeout` tool error the planner reads |
  | Re-simulation | `TOOL_TIMEOUT_SECONDS` | `120` | `504 timeout` |
  | Background graph run | `SESSION_TIMEOUT_SECONDS` | `900` | The session fails with a reason |

  - **LLM attempt.**
    - `RetryingProvider(timeout_s=...)` wraps every attempt in `asyncio.timeout`. An attempt still waiting is cancelled and is a `TransientLLMError` ("no answer within 60 s"), so it is retried, then the fallback provider answers. After that the agents degrade as before (ADR 0049, 0050, 0053) instead of failing the session.
    - `build_provider` passes the same seconds to the SDK clients' `timeout`.
    - Replay and Fake are not wrapped. The requests themselves do not change, so every cassette still replays.
  - **Tool call.**
    - `ToolRegistry(timeout_s=...)` wraps every handler. A call still running is `ToolError(code="timeout", message="<tool> took longer than 120 s and was stopped")`, which the planner reads like any tool error.
    - A handler's `asyncio.to_thread` worker cannot be cancelled, only abandoned. The optimiser's own wall-clock nets still stop a solve (ADR 0055).
    - The API's planning stack passes the setting. `make record-cassettes` and the eval harness build their stacks without one, so a slow machine never changes what they record or score.
    - The default is above run_optimizer's 60 s + 30 s solver nets, so a solve that would finish is never cut short.
  - **Re-simulation.** `POST /api/plans/{id}/simulate` gets the same limit through `PlanService(timeout_s=...)`. A re-simulation still running is `504 timeout` ("The simulation took longer than 120 s and was stopped.") and stores nothing.
  - **Background graph run.**
    - `SessionService(session_timeout_s=...)` bounds each background run: the start, and the resume after clarify or amend.
    - A run that has not paused by then is cancelled. The session gets a `DecisionMade` trace event, `decision="session_timed_out"`, with no node and the reason as its summary. It then fails with the reason "Planning took longer than 900 s and was stopped.", so the SSE stream shows the event and then `end`.
    - `failed` stays terminal, after an amend run too. A reverting amendment would need a checkpoint rewind.
    - The decision event reuses an existing payload, so the SSE contract and the timeline need no change.
    - Approve and reject run within their request and are instant (ADR 0046), so they have no timeout.
  - **What stays unchanged.**
    - The optimiser's work budgets and wall-clock nets (ADR 0055).
    - No blanket request timeout on the API: retrain holds its request 40–90 s by design (ADR 0026), and SSE streams are long-lived.
    - The web proxy keeps undici's defaults (300 s for headers and between body chunks; FastAPI's SSE pings every 15 s keep a stream alive).
  - We rejected failing the session on any single LLM or tool timeout. That is the literal reading of the acceptance criterion, but it would bypass the graceful degradation of SF-03. The criterion is proved with a stalled LLM or planner and a small `SESSION_TIMEOUT_SECONDS`.
- **D8. A failed session's reason stays a string.** `SessionResponse.error` has no code: a code would need a database column (migration 0015) for no reader.
- **D9. Tests.**
  - `tests/api/test_errors.py` checks:
    - the schema and `X-Request-ID` on 404, 409, 413 (declared and chunked), 422 (each oversized input, a validator's message, a whole-body rule, every problem listed, malformed JSON, a bad path parameter, too many answers, an oversized key or query) and 503;
    - a 500 that shows neither the exception's text nor a traceback;
    - an OpenAPI contract with every error referencing `ErrorResponse`.
  - Unit tests cover the LLM-attempt timeout (a provider that never answers, retried, then falling back), the tool timeout, the configuration and the simulate 504.
  - Integration tests fail a session whose LLM or planner stalls, with its reason, its trace event and the stream's `end`.
  - Vitest covers the reader, the shared component, the limits contract and the reference ids the clients carry.
- **D10. The frontend reads and shows errors one way.**
  - `apiError(response)` in `lib/api/reason.ts` replaces `responseReason`, `validationMessage` and `detailMessage`. It returns `{message, code, referenceId, status}`, takes the reference id from the body or `X-Request-ID`, and still reads FastAPI's older list and falls back to `HTTP <status>`.
  - Failed results carry `referenceId`. `CatalogRequestError`, `ModelsRequestError` and `SessionLoadError` extend `ApiRequestError`, which carries it too.
  - `ErrorMessage` shows the message inline, as ADR 0066 D8 has it, and a "Reference: <id>" line when there is one. `ReferenceId` adds that line to alerts that lay out their own message.
  - Every error display uses them:
    - brief composer, clarification, amend, approve and reject, accepting a relaxation;
    - re-simulate, retrain;
    - the session, models and data pages' load errors;
    - competitor prices;
    - a failed session's reason.
  - Session creation, session loads and model lists now show the API's message instead of `HTTP <status>`. The proxy's 502 answers the schema with its own reference id.
- **D11. Configuration** is `LLM_TIMEOUT_SECONDS`, `TOOL_TIMEOUT_SECONDS`, `SESSION_TIMEOUT_SECONDS` and `MAX_REQUEST_BODY_BYTES`, following `OPTIMIZER_TIME_LIMIT_SECONDS`, and documented in `.env.example`.

## Consequences

- One reader and one component handle every API error, and a quoted reference id finds the request in the logs once #71 puts it on every line.
- #70's 429 and #72's replay-miss error only add a code.
- A timed-out session cannot be amended back to its previous revision. The planner now sees a new tool error code, `timeout`, only when a tool is actually stalled.
- An abandoned tool thread keeps its CPU until its own nets stop it, so a machine that times out a tool once is still busy for a while.
