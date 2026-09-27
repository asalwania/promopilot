# A stored plan is re-simulated through its session: the latest plan revision, on the latest demand model, replacing its stored simulation

E7 (#40) adds `POST /api/plans/{id}/simulate` (SPEC §10, user story 16 on #9). It re-simulates a stored plan revision with a bounded run count, returns the result and stores it against the revision. ADR 0042 already fixes the run bounds (100 to 5,000), the seed (`SIMULATION_SEED`, never set by the API) and that the new result replaces the stored one. SPEC and the issue left three questions open. We chose these with the owner (D1–D3 on #40):

- **D1. `{id}` is the planning session's id, and the plan is its latest plan revision**: the one `GET /api/sessions/{id}` shows. A plan revision has no id of its own: its key is the session and its number.
  - An unknown session, or one with no plan revision yet (still planning, or failed), is `404`.
  - The revision's number and plan lines stay as they are. Only its `simulation` changes, in the column migration 0006 added, so no migration is needed.
  - When E8's amendments add revisions, the latest is the one on screen. An optional revision number can be added to the request later without breaking it.
  - We rejected a revision number in the body now, which nothing needs before E8. We also rejected giving each revision its own UUID, which needs a migration and a new id in the read model.
- **D2. The revision is simulated on the latest demand model**, resolved per call like every tool and the planner (ADR 0025).
  - Neither the revision nor its simulation records the model it was planned on. After a retrain, the new ranges can therefore drift from the plan lines' stored expected numbers. The response names the model it used (`demand_model`).
  - We rejected storing the model version with the simulation, and re-simulating on the exact model version the plan used. The second would need that version stored on the revision and loaded from the registry.
- **D3. `competitor_reaction` is reserved and only `null` for now.** The contract carries the field so #41 can widen it to the scenario's real type without renaming anything. Any other value is `422`.
  - We rejected defining #41's shape now (a match probability) and rejecting it until then, which commits #41 to a shape early. We also rejected accepting any value and ignoring it, which misleads the caller.

The details below follow from those choices and from ADR 0042:

- **Request** `{n_runs, competitor_reaction}`, both optional. `n_runs` defaults to `SIMULATION_RUNS`, as for the `simulate_plan` tool. Outside 100–5,000 it is `422`, as is an unknown field.
- **Stock basis.** Units are capped at the pooled available stock of the planning request's as-of week: the snapshot the plan was planned on.
- **Seed.** `SIMULATION_SEED`. So the same revision, run count and model always give the same result, and re-simulating with the stored run count reproduces the stored simulation.
- **Response** `{session_id, revision_number, demand_model, as_of_week, simulation}`, where `simulation` is the `PlanSimulation` now stored on the revision.
- **Errors.** No trained demand model, or no inventory snapshot for the as-of week, is `503`. A stored plan the latest model cannot simulate (for example a SKU it no longer knows) is `409`.
- **Any session with a plan revision can be re-simulated.** Approval does not exist until E8.
- **One code path.** The `simulate_plan` tool and the endpoint share `simulate_on_latest_model` (the model lookup, the stock snapshot, the simulation and its error codes). `SessionStore.save_simulation` replaces a revision's stored simulation.

## Consequences

- The UI (E10) can offer "re-run with more runs", and after #41 "re-run with competitor reaction", on the plan on screen, and read the new result back from the session read model.
- Two re-simulations of one revision at the same time both succeed. The last write wins, and both writes are valid results for that revision.
