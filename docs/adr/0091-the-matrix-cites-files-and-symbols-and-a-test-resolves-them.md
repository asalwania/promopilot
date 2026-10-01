# The evidence matrix cites files and symbols, not line numbers, and a test resolves every citation

#77's brief asked for a real code location (`path:line`) in every SPEC §16 row, verified to exist. SPEC §16 asks only for "evidence in code", and ADR 0089 D10 fixed how tests are cited (pytest node ids). It left the form of a code citation open.

## Decisions

- **D1. A code citation is a file and a function or class**, written as `` `optimizer/solver.py` `solve` ``, with paths under `backend/src/promopilot/`. Frontend files and tests are cited by their path from the repository root.
  - A line number is true on one commit only. The files cited here (`solver.py`, `options.py`, `relations.py`, `graph.py`) change in most tickets, so a line number would be wrong after the next merge, and nothing would say so.
  - A function name survives a move inside a file, and a rename breaks a test (D2) instead of the claim.
- **D2. `backend/tests/tools/test_nine_blocker_matrix.py` reads `docs/nine-blocker.md` and checks every citation.** It runs with the unit tests, so CI fails on drift.
  - Every `` `tests/…py::test_name` `` names a file that exists and defines that function.
  - Every `` `file.py` `` followed by `` `symbol` `` names a file that exists and defines that function or class.
  - Every other cited `.py`, `.ts`, `.tsx` or `.yaml` path exists, and every cited scenario is a file in `backend/evals/scenarios/`.
  - Every relative link resolves.
  - It reads no number: the numbers come from one published report (ADR 0089 D2), and a test of them would only repeat the report.
- **D3. Demo moments are checked by hand against the committed recordings** (`backend/cassettes/`, the Explainer requests hold each recorded revision's plan data), because no test can say that a recorded plan shows a feature. Where a recorded plan does not show one, the document says so and cites a test and an eval scenario instead (ADR 0089 D9).
- **D4. A link to a document that does not exist yet is a `LATE` marker, not a dead link.** The relative-link check would fail on it, and #75's architecture document lands in its own PR.

## Consequences

- A reviewer can open each citation by name and search for it; the test keeps the names honest.
- Renaming a cited function or test means editing the document in the same PR, which is the point.
- The check does not prove that a cited test tests what the sentence says. That stays a review matter.
- No code, API, setting or cassette changes.
