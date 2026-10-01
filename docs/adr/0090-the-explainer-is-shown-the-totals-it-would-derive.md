# The Explainer is shown the totals and the budget left it would otherwise work out itself

#185: while recording #142's `infeasible` app session (a ₹10k budget with a 95% clearance target), two of three live recordings failed. The Explainer's summary for revision 1 cited ₹4,904, a figure in no tool output. The grounding guard caught it, the Explainer fell back to its template (ADR 0050), and `record-cassettes` refused both recordings.

## What the cause was

The failed recordings were not kept, but the recorded `infeasible` session still holds the Explainer's first answer to that request, the one the guard rejected and regenerated (`cassettes/7807d6b8…json`). Its summary reads: "an incremental profit of ₹4,904 with a promo cost of ₹8,631". The plan data shows the two lines' amounts, not their totals:

- ₹4,904 is ₹4,415 + ₹489, the two lines' `expected_incremental_profit`;
- ₹8,631 is ₹3,934 + ₹4,697, their `promo_cost`.

So the cause is the one the issue suspected, with a different sum: the LLM adds up what the data lists. The rule that the LLM never computes numbers (ADR 0028, ADR 0050) was in the prompt, but the data left a total as the natural thing to write. The same applies to the budget left (₹10,000 minus the spend) and the total clearance shortfall, which the data also leaves to the reader.

## Decisions

- **D1. `plan_data` carries `plan_totals`.** `promopilot.guardrails.plan_totals` computes, from the revision and the marketing budget, with no LLM, and the Explainer only formats the result. The arithmetic lives in guardrails, not in `promopilot.agents`, which an architecture test keeps free of business arithmetic (ADR 0002):
  - `expected_units`, `promo_cost` and `expected_incremental_profit`: the sum over the plan lines;
  - `marketing_budget_left_at_expected_promo_cost`: the marketing budget minus that promo cost;
  - `marketing_budget_left_at_planned_promo_cost`: the marketing budget minus the plan's promo cost at its safety-margin quantile, what the budget constraint actually counted (ADR 0080); absent for a revision with no safety margin;
  - `clearance_shortfall_units`: the sum of the shortfalls.

  The guard checks an answer against the same data, so these figures are in its allowed set. A figure still absent from the data, such as ₹4,905, stays ungrounded (a test pins it).
- **D2. A total adds the amounts as the lines show them.** Each line's amount is rounded to whole rupees (units to whole units) before it is added, so the total equals the sum of the figures the LLM sees. Adding unrounded values would give ₹8,632 for ₹3,934.4 + ₹4,697.2 while the lines show ₹3,934 and ₹4,697, and the LLM adding them would reach ₹8,631 and fail the guard. The total is within the rounding of the exact sum (at most half a rupee or unit per line).
- **D3. The prompt names `plan_totals` and forbids the rest.** Prompt v3 says where totals, differences and amounts left are, and that the LLM must never add up the lines, subtract a cost from a budget or work out any other total or difference: if the data does not show a figure, describe it in words or cite the figures the data does show. The regeneration message after an ungrounded answer says the same.
- **D4. A refused recording dumps the Explainer's requests and answers.** `record_cassettes` takes `failed_dir`. When a run is refused it copies there each Explainer cassette the run recorded live (a request and the answer it got, so the Explainer's whole input is kept), and says so in the error. `python -m promopilot.cassettes` passes `cassettes/failed/`, which is git-ignored. Cassettes the run only copied in from earlier recordings are not dumped. A successful run writes nothing there. The eval recorder (`make record-eval-cassettes`) already keeps every cassette it records, so it needs nothing.
- **Rejected: showing only the figure the issue named (the budget left).** The failing figure was a sum of the lines. Any total an LLM may be tempted to write needs to be in the data, and these are the ones a plan summary naturally states.
- **Rejected: loosening the guard to accept sums of cited figures.** Grounding checks numbers against tool outputs, not against what the LLM could compute from them (ADR 0028).
- **Not covered: differences between figures the data shows as before and after.** The diff already carries `change` for the objective and the promo cost (ADR 0052), and `relaxation.changes` carries each limit's change as a percentage. A change in a rupee limit the data shows only as `from` and `to` is still left to the reader. Add it here if a recording shows one.

## Consequences

- **Every Explainer cassette is stale.** The prompt text and the plan data are in the request, so every Explainer request hashes differently: the app's `cassettes/` and the eval's `evals/cassettes/` need their Explainer calls re-recorded (`make record-cassettes`, `make record-eval-cassettes`, live). The Context, planner and Critic requests are unchanged, so those cassettes keep replaying. Until then `check-cassettes`, the committed-cassette tests and the eval replays report a cassette miss on every Explainer request.
- **The fix is confirmed offline, not live.** Tests show the totals in the Explainer's input, that an answer citing them is grounded, and that a total the data does not show is still rejected. Whether the live model now stops deriving figures is only known by re-recording.
- There is no migration, no new configuration and no API change.
