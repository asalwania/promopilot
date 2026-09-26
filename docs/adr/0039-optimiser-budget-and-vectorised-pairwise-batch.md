# The 10 s optimiser budget covers `solve` only, and the pairwise batch is vectorised with lines told apart by identity

After #109 retuned the demo world (ADR 0037), `solve` took about 18 s on the seed-42 demo brief. About 14 s of that was `pairwise_cannibalisations`. SPEC §6 and the E6 exit ask for an optimiser under 10 s. #112 speeds up the pairwise batch. Profiling it settled two questions that the issue, SPEC and ADRs 0033 and 0036 left open, and we chose both with the owner.

## Where the time went

- The solver hands the batch every pair of eligible options that could run together: 415,524 on the demo brief. Only 3,796 of them have a term that is not 0.
- Most of the 14 s was per-pair pandas work. The substitute check read a relations column about 500,000 times, and every live pair filtered the `line_paths` rows with `isin`.
- Candidate generation, which comes before `solve`, takes 7–9 s on its own: `DemandModel.predict` about 7 s and `line_effect_totals` about 1.5 s. CP-SAT takes about 4.5 s. So generation plus `solve` stays over 10 s even with the pairwise terms at zero, and #112 could not make it fit.

## Decision

- **The 10 s budget is for `solve` only.** That is the pairwise terms plus CP-SAT, for a candidate set already generated. This matches SPEC's "optimiser under 10 s" and the E6 exit criterion. #112's second acceptance criterion originally counted generation too, and was read this way (decision comment on #112).
  - Generation's time is reported separately.
  - Its speed-up is follow-up #113: `DemandModel.predict`, `line_effect_totals`, and indexing the relations lookups.
- **The `model`-marker test times `solve` on the fitted seed-42 world.** The world is fitted and the candidates generated first, untimed. `solve` then runs twice, and the faster run must be under 10 s.
  - Taking the faster of two runs keeps one stall on a busy laptop or CI runner from failing the test.
  - Both runs use the same seed and give the same plan.
- **`pairwise_cannibalisations` is vectorised across pairs, and its numbers are unchanged.**
  - Whether a pair has a term (same region, a common week and segment, a detected substitute between them) is decided on arrays. The substitute check is done once per pair of distinct SKU sets.
  - Each line's own-SKU change is cumulated over the weeks, and so is the baseline of SKUs both lines move. So a pair's overlap is one subtraction.
  - `pairwise_cannibalisation`, for one pair, is now written out directly and no longer calls the batch. A property test checks that the batch equals it to the paisa on random pairs.
  - On the demo brief all 415,524 terms match the old code within ₹4 × 10⁻¹³, and the plan is the same.
- **The batch tells lines apart by object identity, not equality.** Hashing 830,000 frozen pydantic `PlanLine`s cost more than the arithmetic. The solver passes the same line objects in every pair. A caller that passes an equal line as two objects gets the same numbers; that line is just predicted twice.
  - We rejected keying by equality: slower, for no difference in results.
  - We rejected dropping pairs in the solver's pre-filter. Every term that is not 0 is kept, as ADR 0036 decided.

## Consequences

- On the demo brief the pairwise batch takes about 1.4 s instead of about 14 s. `solve` takes about 6–7 s: about 4.5 s of CP-SAT and about 2 s of pairwise terms and pair set-up.
- Generation plus `solve` is still about 14–16 s, until #113 speeds up generation. The planning session's 60 s budget for a full plan (SPEC §6) is not at risk.
- The `model`-marker test fits the full seed-42 world, which adds about 1.5 min to `make test`.
