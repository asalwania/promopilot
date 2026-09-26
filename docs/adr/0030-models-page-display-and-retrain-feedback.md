# The models page groups versions by kind, times the retrain, and reports its outcome inline

E10 (#67) adds `/models`: the model registry with metrics and a retrain button (SPEC §11, SF-02). It reads `GET /api/models` and triggers `POST /api/models/retrain`, which holds the request 40 to 90 seconds until the new model is live and answers `409` when a retrain is running or no data is loaded (ADR 0026). The spec does not say how metrics are shown, how progress looks during that wait, how failures surface, when the list refreshes, or how the manager finds the page. We chose these with the owner:

- **One card per model kind, one row per version, newest first.** Each row shows the version, a Live badge on the model the API serves, the training time in en-IN local time and the as-of week (`W105`). `kind` is read as any string and titled generically (`Demand model`), so the relations model (E5) appears without a frontend change.
- **Metrics are columns, with readable labels for known keys.** The WAPEs show as percentages (`WAPE, region × SKU` 14.1%), `response_skus_fitted` as a whole number and `elasticity_median_std_error` to 3 decimals. An unknown key shows under its raw name to 3 decimals. A version without a metric shows `—`.
- **Retrain shows a spinner and an elapsed timer, not a progress bar.** While the request is open, the button is disabled and reads "Retraining…", with "0:37 elapsed · usually about a minute". The API reports no progress, so a percentage would be invented.
- **The outcome appears inline under the button.** Success says "Version N is live" and reloads the list. A failure says "Couldn't retrain: " plus the API's `detail` (the 409 reasons, the proxy's "API unreachable") or `HTTP <status>` when there is none, or the network error. We rejected toasts, which need a new component and vanish before a 90-second wait is over.
- **The list loads when the page opens and after our own retrain.** It does not poll. A failed read retries twice, then shows "Couldn't load models" with the reason and a Retry button, as the session page does (ADR 0021).
- **A small header nav in the root layout links Home and Models.** `/evals` and `/data` join it when they exist.

## Consequences

- A retrain started from another tab or `make train` appears only after a reload or our own retrain.
- Leaving the page does not cancel a running retrain (ADR 0026); coming back shows the new version once it is registered.
