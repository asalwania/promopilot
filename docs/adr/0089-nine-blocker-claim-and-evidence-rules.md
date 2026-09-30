# The nine-blocker claim is kept at D2 only by a stated rule, on numbers from one clean live recording

E12's #77 asks for `docs/nine-blocker.md`: the F3 × D2 claim, its justification, SPEC §16's evidence matrix filled in with code, tests, demo moments and eval metrics, and the final eval numbers from the latest full report with its timestamp. If most D2 targets fail, the claim is downgraded to D1 (SPEC §2.1, §12.3; spec #14).

What we found at the #77 gate (2026-09-30):

- **The committed report is stale.** `backend/evals/published/latest.*` is #58's live run of 2026-09-29 (32 scenarios, ADR 0073). It predates the substitute rule (ADR 0075), regret by cause (ADR 0078), accepted relaxations in code (ADR 0083), the safety margin (#159, ADR 0080), SKU limits (#141, ADR 0084) and the feasible demo (#142, ADR 0086), and the eval cassettes on main miss for many runs.
- **SPEC's downgrade wording differs.** SPEC §2.1 says "if D2 targets are not met"; #77 and §12.3 say "if most D2 targets fail". Some targets were missed in the stale run (regret median, constraint satisfaction), so the rule decides the claim.
- **Consistency cannot be measured under replay.** A scenario's replayed runs are identical by construction (ADR 0063 D13).
- **SPEC §16 describes F-07 as a "per-region solve".** The optimiser runs one joint solve over region-level plan lines with pooled stock (ADR 0004).
- **Some features have no recorded demo moment.** No recorded session plans a regional holiday; bundles and halo depend on what the re-recorded sessions hold.

We chose the following with the owner at the #77 gate (D1–D13, every recommended option).

## Decisions

- **D1. Document form.** `docs/nine-blocker.md` has a compact §16 table, one subsection per row with the full evidence, then the final numbers, the misses and how to reproduce them.
- **D2. One source for the numbers.**
  - Every number comes from the main session's clean live recording of all 33 scenarios, run after #159, #141 and #142 merge, which the main session publishes to `backend/evals/published/`.
  - The document cites that report's `generated_at`, provider, scenario count and commit.
  - Until then every number is a placeholder marked `<!-- LATE: ... -->`, the same convention as #75.
- **D3. The claim rule.**
  - D2 holds when most of the 13 targeted §12.2 metrics pass (constraint satisfaction, extraction, clarification, infeasibility handling, grounding, elasticity recovery, substitute precision and recall, complement precision and recall, plan quality, regret, consistency) **and** constraint satisfaction, clarification behaviour, infeasibility handling and grounding each pass or miss only narrowly with a stated cause.
  - Otherwise the claim is D1, in the document and the deck.
  - Every miss is listed with its cause and ticket, whichever way the rule falls.
  - SPEC §2.1 gets a note pointing here.
- **D4. Consistency** comes from a supplementary live `make eval RUNS=5 SMOKE=1` run by the main session, cited with its own timestamp.
- **D5. F-09 keeps "—"** as its eval metric. The simulator's determinism, quantile order and speed are tested; its accuracy is not scored against the oracle, and E12 adds no new metric.
- **D6. AG-01…AG-06** get their own table after the §16 matrix, since evaluation criterion 5 is judged separately.
- **D7. SPEC §16's F-07 cell** now reads "one joint solve over region-level plan lines (ADR 0004)".
- **D8. The latency miss is listed.** SPEC §6's 60 s full-plan requirement is an NFR, not a §12.2 target, but a miss is stated with the LLM and own-work split, as is cost against ₹20.
- **D9. No recorded demo moment:** the document cites the eval scenario and a unit test that show the feature, and says it is not in the demo recordings.
- **D10. Tests are cited as pytest node ids** (`backend/`-relative, `path::test_name`) and frontend paths, one to seven representative tests per cell.
- **D11. This ADR is 0089.** 0087 is #113's and 0088 is #75's.
- **D12. The numbers live only in `docs/nine-blocker.md`.** The README and the architecture document (#75) link to it rather than copy them.
- **D13. The main session refreshes `backend/evals/published/`** in its re-record; #77 only cites it.

## Consequences

- The claim can be checked: each number in the document traces to one committed report, and each row to code and tests a reviewer can open.
- Filling the document in is a separate step after the re-record: search `docs/nine-blocker.md` for `LATE:`.
- A downgrade to D1, if the rule falls that way, changes the document, the README link text and the deck, not the code.
- No code, API, setting or cassette changes.
