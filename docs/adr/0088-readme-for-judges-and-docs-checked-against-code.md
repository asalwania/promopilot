# The README is a short entry point for judges, the reference moves to docs/, and the tool contracts and agent-graph diagram are checked against the code

E12's #75 asks for three things:

- a README a reviewer can run and understand the project from alone: what, why, quickstart, an architecture overview, commands, API docs, evals, the claim, credits and the video;
- an architecture document with the process flow, the agent graph as built, and tool contracts "generated from the tool registry's schemas where practical";
- model usage and a feature → implementation table for F-01…F-09, linked to the ADRs and CONTEXT.md (SPEC §15 E12, spec #14).

**Why the README had to change.** It had grown to about 570 lines (107 KB). Every ticket since E3 added the reference for its module to it, as CLAUDE.md asks. That reference is valuable, but a judge meets it before they learn what the project does.

**Facts that land late.** The final eval numbers, the demo video link, screenshots and the optimiser timings (#113) all arrive after this ticket.

**What SPEC leaves open:**

- where the reference goes;
- how the diagrams are made and kept true;
- how tool contracts are generated;
- where late facts live.

We chose the following with the owner on #75 (D1–D12, every recommended option).

## Decisions

- **D1. The README becomes a short entry point, and the reference moves to `docs/guide/`.**
  - The README, about 200 lines, covers what PromoPilot does, why, the claim, the quickstart for the demo and for development, an architecture overview, commands, the API, evals, a documentation map, credits and licence.
  - The per-module reference moves, lightly edited, into `docs/guide/*.md`. Nothing is dropped.
  - Links into the old README sections follow it, including the error-code link that `tools.api_docs` writes into `docs/api.md`.
  - We rejected two alternatives. Folding the reference into the architecture document would bury the architecture. Keeping the long README with a judge's section on top would still be 100 KB.
- **D2. Tool contracts are generated into `docs/tools.md` by `backend/tools/tool_docs.py`.**
  - It builds the registry the way the API does, through `planning_stack`, with inert dependencies: building a tool only binds them. It renders `ToolRegistry.specs()`, the exact descriptions and JSON schemas the LLM is shown.
  - Each tool gets its description and input and output field tables. Each shared schema appears once, rendered by the same helpers as `docs/api.md` (ADR 0082). The page also lists the tool error codes. Two different schemas sharing one name are refused.
  - Company policy and the planning settings take their defaults, never the environment's values, so the page is the same on every machine. It is written as UTF-8 with LF endings.
  - `make tool-docs` writes the page, and `make api-types` runs it after `make api-docs`, so a ticket that already regenerates the contract regenerates the tool docs too.
  - Two checks catch drift. `make test` renders the registry and compares it with the committed page. CI's contract job fails when `make api-types` changes `docs/tools.md`.
  - The architecture document keeps a short hand-written table of the tools (what each returns, what it is built on, which features it serves) that links into the generated page.
  - We rejected a compact generated table spliced into the architecture document, which would be too thin to be a contract, and a hand-written list, which would drift.
- **D3. The agent-graph diagram is hand-written Mermaid, and a test ties it to the code.**
  - The `stateDiagram-v2` in `docs/architecture.md` labels each edge with why it is taken.
  - `backend/tests/architecture/test_architecture_doc.py` compiles `build_graph` with inert tools and asserts that the diagram's edges equal the compiled graph's.
  - We rejected LangGraph's generated `draw_mermaid()`: its edges carry no reasons, and its markup is noisy. We also rejected an unchecked hand-drawn diagram.
- **D4, D5. The eval numbers are hand-kept, cite their report, and live in one place.**
  - Headline numbers are copied from the published eval report with its timestamp, never computed by a script.
  - #77 later placed the claim and all the numbers in `docs/nine-blocker.md` (ADR 0089). The README therefore links to that document for them rather than copying them.
  - The architecture document quotes no eval number or timing, so it cannot go stale.
- **D6, D7. The claim is stated as SPEC §2.1 states it.** The architecture document explains how the evidence is produced: the hidden ground truth, the oracle, the eval harness, the tests and the CI checks. The §16 evidence matrix lives only in `docs/nine-blocker.md` (#77).
- **D8. The ADR index moves to `docs/adr/README.md`.** GitHub shows it when the folder is opened. The README and the architecture document link to it.
- **D9. The README gets a Credits section.** It names the main open-source projects PromoPilot builds on and their licences, the agent skills used to build it, and that it was built with Claude Code.
- **D10, D11. Late facts sit in marked slots.**
  - Each fact that landed after this ticket (the video link, a screenshot, the headline results, timings) appeared once, marked with an HTML comment starting `LATE:`.
  - Searching for `LATE:` listed everything left to update before submission (#81). The results were filled in from the published reports before merge, no screenshot was added, and only the demo video link is still marked.
- **D12. The README move is the ticket's last commit.**
  - The PRs in flight for #159, #141 and #142 all edit README.md, so the architecture document, the tool docs and their tests landed first.
  - The README restructure and the move to `docs/guide/` are one mechanical commit made after those PRs merged, so no one had to port their README edits into the new layout.

## Consequences

- **Tool-schema changes.** A ticket that changes a tool's description or schemas must run `make tool-docs` (or `make api-types`) and commit `docs/tools.md`. Otherwise `make test` and CI's contract job fail, naming the file. Tool schemas were already part of every recorded planner request's hash (ADR 0049), so such a change already needs a re-recording.
- **Graph changes.** A ticket that changes the graph's edges must update the diagram in `docs/architecture.md`.
- **Where new reference goes.** A module's new reference goes in its `docs/guide/` page, not the README. The README changes only when what a judge needs to run or understand the project changes.
