# Every log line names its request and session; a manager's text shows only at debug, and secrets never

E11's #71 asks that incidents can be traced safely (SPEC §6, SF-01, spec #13). structlog JSON lines should carry a request id from middleware and the session id on every line, briefs should be logged only at debug level, and secrets should be redacted. The acceptance criteria:

- a test captures the logs of a request and finds its request id and session id on each line;
- at info level, no brief text or API key appears in the logs.

Before #71:

- **Session ids.** ADR 0047 bound `session_id` in a session's background run, in its decision requests, and with `node` inside each traced graph node. Creating a session, reading one, its event stream and re-simulating a plan were not covered.
- **Request ids.** ADR 0071 gave every request an id, `X-Request-ID`, but only the 500 line (`api.unexpected_error`) logged it.
- **Levels and redaction.** There was no level filter, so debug lines always printed, and nothing redacted anything.
- **Standard-library lines.** Uvicorn, httpx, LangGraph and the LLM SDKs printed plain text with no ids.
- **Brief text.** Nothing logged a brief on purpose. But several warnings logged `error=str(error)`: `context_fallback`, `llm_retry`, `llm_fallback`, `planner_llm_failed`, `planner_restarted` and `critic_feedback_fallback`. An LLM answer that fails validation surfaces as pydantic's text, which quotes the answer as `input_value=...`, and that answer can echo the brief. A provider's 401 text can carry a key or a masked one.

We chose the following with the owner on #71 (D1–D10, every recommended option).

## Decisions

- **D1. The request guard binds the request id.**
  - `RequestGuard`, ADR 0071's pure ASGI middleware, binds `request_id` with `structlog.contextvars` for the whole request. The exception handlers, the 500 line and the access line all carry it.
  - It is added last, so it is the outermost middleware, and a 429 from #70's limiter carries the id too.
  - A background run a request spawns keeps that request's id: `asyncio.ensure_future` copies the context. A run's lines therefore name the request that started or resumed it, next to `session_id`.
  - A client's own `X-Request-ID` is still ignored (ADR 0071 D4).
- **D2. A route with a `session_id` in its path binds it.**
  - `install_error_handling` adds an app-level dependency, `bind_path_ids`. Every route included after it, current or future, binds `session_id` for the request, with no per-route change. That covers `/api/sessions/{session_id}/…` and `/api/plans/{session_id}/simulate`.
  - A path value that is not a UUID is the client's own text. It is never bound, and the route answers 422.
  - `SessionService.start` binds the new id once the session row exists. The background run, `traced_node` and the decision requests bind it as before.
  - Lines logged at startup belong to no request, and carry no ids.
- **D3. One access line per request.**
  - When a request ends, `RequestGuard` logs `http.request` with `method`, `route` (the template, such as `/api/sessions/{session_id}/amend`), `status` and `duration_ms`.
  - It also logs the path's `session_id`, read from the matched route. The route's dependency has already unbound it by then; `api.unexpected_error` reads it the same way.
  - The raw path and the query string are never logged. An unmatched path has `route: null`.
  - The healthcheck routes (`/health`, `/api/health`) log at debug, so the container's healthcheck does not fill the logs.
  - An SSE stream's line is logged when the stream ends.
  - Uvicorn's own access logger is disabled, so there is no second, plain-text line. This replaces ADR 0047's "Uvicorn's own access logs are not changed".
- **D4. Standard-library lines take the same path.**
  - `configure_logging` installs one root handler with structlog's `ProcessorFormatter`. Uvicorn, httpx, LangGraph, SQLAlchemy, psycopg and the SDKs then write JSON (or console) lines with the bound ids, and pass the same two guards (D6, D7).
  - Uvicorn's own handlers are removed, so its lines propagate to that handler.
  - The root level is `LOG_LEVEL`. `anthropic`, `openai`, `httpx` and `httpcore` never log below info: their debug lines dump whole LLM requests, responses and headers.
  - Configuring again replaces the handler, so no line is written twice.
- **D5. `LOG_LEVEL`.**
  - The values are `debug`, `info`, `warning` and `error`, in any case, and the default is `info`. structlog filters with `make_filtering_bound_logger`.
  - `LOG_FORMAT` stays `json` by default everywhere, including `make dev`.
- **D6. Secrets are redacted on every line, at every level.**
  - **Where.** A processor runs last before rendering, over every value, through dicts, lists and tuples. That includes the event text and the traceback. `format_exc_info` now runs in console mode too, so a traceback is text before it is redacted.
  - **Secret-named fields.** A field whose name is, or ends in `_`/`-` plus, `api_key`, `apikey`, `password`, `passwd`, `secret`, `token`, `authorization` or `cookie` becomes `[REDACTED]`. Case does not matter, and counts such as `input_tokens` do not match.
  - **Patterns inside any text.**
    - An OpenAI or Anthropic key (`sk-…`, `sk-proj-…`, `sk-ant-…`), masked ones included. It is not matched inside a word, so `task-…` stays.
    - A `Bearer` token and an `x-api-key` value.
    - A URL's password: `scheme://user:[REDACTED]@host`.
  - **The configured keys.** `build_app` passes the values of `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` (`Settings.log_secrets()`), and those are redacted wherever they appear, whatever their shape. Values under 8 characters are ignored.
  - The database password is not matched as a bare value. The default, `promopilot`, would blank the project's name on every line, logger names included. The URL pattern covers it.
  - We rejected patterns alone, which miss a key of an unknown shape, and an allow-list of fields, which breaks on every new field.
- **D7. A manager's text appears only on debug lines.**
  - **Which fields.** `brief`, `amendment`, `answers` and `rejection_reason` hold what a manager wrote. `messages`, `prompt` and `completion` would hold an LLM body. These are `promopilot.logs.MANAGER_TEXT`.
  - **The guard.** On any line above debug, such a field's value becomes `[withheld: N chars]`, and any `input_value=...` a validation error quotes becomes `input_value=[withheld]`. The event and its other fields stay, so `context_fallback` still says why. A debug line shows everything, still redacted.
  - **New lines.** The session service now logs, at info:
    - `sessions.created` (`brief_chars`);
    - `sessions.clarified` (`answer_count`);
    - `sessions.amended` (`revision_number`, `accept_relaxation`, `amendment_chars`);
    - `sessions.decided` (`decision`, `revision_number`).

    Each has a debug twin with the text: `sessions.brief`, `sessions.answers`, `sessions.amendment` and `sessions.rejection_reason`.
  - **Unchanged.** Every existing event name and field, including `planner_call_refused`, `llm_no_fallback` and `llm_retry`, and the trace events. Nothing parses the logs; evals and metrics read trace events.
- **D8. The CLIs are unchanged.**
  - `make eval`, `make record-cassettes`, `--check` and `make train` keep structlog's default console output, so what they print is unchanged.
  - Only the API process configures logging.
- **D9. Tests.**
  - **`tests/unit/test_logs.py`.**
    - Level filtering.
    - Redaction: field names, key patterns, Bearer, `x-api-key`, URL passwords, configured keys, nested values, and exception text in both formats.
    - The guard: withheld at info, warning and error, shown at debug, and a quoted `input_value` cut.
    - Standard-library lines as JSON with the bound ids; uvicorn's access line silenced; the SDKs capped at info; no duplicate line on reconfiguring.
  - **`tests/api/test_request_logs.py`** (offline).
    - Every line of a request carries its `X-Request-ID`.
    - The access line has the route template and neither the path's text nor the query.
    - Session and plan routes bind the session id; a non-UUID path binds nothing.
    - Nothing stays bound after the request.
    - The 500 line carries both ids; 413 and 429 requests have access lines.
    - Health checks log only at debug.
  - **`tests/integration/test_session_logs_api.py`** (Postgres, FakeProvider).
    - Every line of a clarify request, and of the background run it resumes, has the request's id and the session's id.
    - At info, a marker in the brief, the amendment and the rejection reason never appears, and neither does an `sk-ant-…` key an LLM error quotes.
    - At debug, the brief appears on `sessions.brief` only.
  - A `tests/conftest.py` fixture puts logging back after every test, since `build_app` configures the process.
- **D10. ADR 0047's logs section** gets a one-line pointer here.

## Consequences

- A quoted reference id (ADR 0071) finds every line of that request in the logs, and the lines of the planning run it started. A session id finds the whole session.
- **Logs keep no text a manager wrote above debug.** Debugging what a manager wrote needs `LOG_LEVEL=debug`, and the trace events and the database still keep every brief, amendment and answer.
- A future field that holds a manager's text must use one of the `MANAGER_TEXT` names, or be added to them.
- **What changes, and what does not.**
  - The request id on a background run's lines is the request that started or resumed it, not the one reading the session.
  - Nothing that goes into an LLM request changed, so every cassette replays (`--check`).
- New setting: `LOG_LEVEL` (`.env.example`).
