# The web proxy forwards `/api/*` paths unchanged, and health is also served at `/api/health`

ADR 0001 has the browser reach the API only through same-origin Next.js route handlers. SPEC names the public API routes with an `/api` prefix (`POST /api/sessions`, `POST /api/models/retrain`), while the health endpoint was `/health` and the Docker healthcheck calls it.

We chose a catch-all route handler (`frontend/src/app/api/[...path]/route.ts`) that forwards `/api/<path>?<query>` to `${API_URL}/api/<path>?<query>` unchanged: same method, headers (minus `host`), body, status and response headers. Request and response bodies stream, so the SSE trace stream (E8) can use the same proxy. The API serves health at both `/health` (container healthcheck) and `/api/health` (browser, through the proxy). If the API cannot be reached, the proxy answers `502 {"detail": "API unreachable"}`.

We rejected stripping the `/api` prefix in the proxy, because the API's own routes would then no longer match the paths SPEC uses, and a request to the API directly (curl, `/docs`) would need a different path than the browser.

## Consequences

- Every browser-facing FastAPI route lives under `/api`; `/health` stays outside it only for the container healthcheck.
- `API_URL` is read by the Next.js server at request time; the browser never learns the API origin.
- `content-encoding` and `content-length` are dropped from proxied responses, because Node's fetch has already decoded the body.
