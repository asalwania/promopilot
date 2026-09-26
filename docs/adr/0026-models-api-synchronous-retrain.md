# Retrain holds the request until the new model is live, one at a time, on the default as-of week and seed

E4 (#29) adds `GET /api/models` and `POST /api/models/retrain` (SPEC §10, SF-02). The E4 spec says retrain "runs in the background and returns the new model id when registered". It does not say whether the request waits, what a second retrain does, which data and seed it uses, or what the list shows. We chose these with the owner:

- **The request stays open until the model is registered.** `POST /api/models/retrain` answers `201` with the new model entry. The fit runs in a worker thread (`asyncio.to_thread`), so the API keeps serving other requests while it trains. On the seed-42 world a retrain takes 40 to 90 seconds, under the 300-second response-header timeout of Node's fetch, which the web proxy (ADR 0018) uses. We rejected `202` with a job id and a polling endpoint, which SPEC does not list, and `202` with a `retraining` flag on the list, which gives the caller no id.
- **One retrain at a time: a second gets `409`.** An in-process lock guards the retrain. A request that arrives while one is running gets `409 Conflict` at once. We rejected letting the second request wait for the running one, and running both, which spends another fit on identical data and registers two identical versions. The lock is per API process, which is enough because the API runs one process (ADR 0020).
- **No request body: the default as-of week and seed 42.** Retrain fits exactly what `make train` fits by default: the as-of week after the loaded history (ADR 0008) and `DEFAULT_SEED` 42. With no sales history loaded it answers `409` with a message telling you to run `make data`. We rejected an optional `{as_of_week, seed}` body: `python -m promopilot.models --as-of-week` covers experiments, and the button on the `/models` page (E10) needs none.
- **The new model goes live at once.** After registering, retrain hands the fitted model to the API's `LatestModel` through `LatestModel.set`, so the planner and `/health` use it without a restart or a reload from disk (ADR 0023).
- **The list is `{models: [...]}`, newest first.** Each entry has `model_id`, `kind`, `version`, `trained_at`, `as_of_week`, `metrics` and `live`. `live` marks the model this API process is serving, which is the latest unless another process registered one since this process loaded. The artifact path stays internal.

## Consequences

- A fit cannot be cancelled once it starts: its worker thread runs to the end even if the client goes away.
- Only the demand model is retrained. SPEC's "demand + relations" gains relations in E5.
- A second API process would need a database lock instead of the in-process one.
