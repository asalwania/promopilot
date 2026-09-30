# The API docs are Markdown generated from the OpenAPI contract by a small stdlib script that `make api-types` runs, and CI fails when the committed page drifts

E12's #76 asks for API documentation generated from the OpenAPI document by a make target. A CI check, next to the existing contract check, must fail when the committed docs drift from the contract, and the README must link the docs (SPEC §10, §15 E12, spec #14 user stories 9 and 16).

SPEC §7.4 already names the page `docs/api.md`, "generated from OpenAPI". SPEC and the spec leave open:

- the generator;
- how the target hooks into `make api-types`;
- the shape of the CI check;
- what the page contains.

**The contract today.**

- It is FastAPI's OpenAPI **3.1.0**, exported by `python -m promopilot.api.openapi` with sorted keys and LF endings.
- The SSE endpoint describes its events with `itemSchema`, a construct from a newer OpenAPI version.
- Every 4xx and 5xx response references `ErrorResponse` (ADR 0071), and four operations document a 429 with `Retry-After` (ADR 0079).
- The contract has no examples.

We chose the following with the owner on #76 (D1–D9, every recommended option).

## Decisions

- **D1. Markdown only, at `docs/api.md`.**
  - GitHub renders it, so a judge reads it in the browser next to the README.
  - The live Swagger UI at `/docs` stays for trying the API.
  - We rejected a static Redoc HTML page, alone or beside the Markdown. It is a committed file of about 1 MB that GitHub shows as source, and it departs from SPEC.
- **D2. An own stdlib-only generator, `backend/tools/api_docs.py`.**
  - Like `tools.coverage_gate`, it is a developer tool, not a product module. mypy strict covers it, and `backend/tests/tools/test_api_docs.py` drove it test-first.
  - **Deterministic.**
    - The output depends only on the contract, and it has no timestamp.
    - Operations and schemas are sorted by the generator, whatever order the document lists them in.
    - The page is written as UTF-8 bytes with LF endings, so Windows and Linux write the same file.
  - **Nothing to install.** It needs no dependency and no network access.
  - **It reads 3.1 and the SSE `itemSchema` as we choose.**
  - **It refuses a page with broken links.** Two headings that would share a GitHub anchor, such as a schema named after a tag, are an error.
  - **We rejected three alternatives:**
    - widdershins: unmaintained since about 2020, built for OpenAPI 3.0, about 200 transitive packages, and verbose code samples per operation;
    - @redocly/cli: HTML only, and hundreds of dev dependencies;
    - openapi-generator: needs Java in CI.
- **D3. `make api-types` runs `make api-docs` as its last step.**
  - `make api-docs` rewrites `docs/api.md` from the committed `docs/openapi.json` alone. It is fast and does not import the backend app.
  - Every ticket that regenerates the contract with `make api-types` regenerates the docs with it, with no new command to learn.
  - We rejected a separate target that CI and developers would each have to remember.
- **D4. The existing contract job checks the docs too.**
  - It is renamed **API contract (generated types and docs up to date)**. Its new step, "Fail if the API docs are stale", diffs `docs/api.md` after `make api-types`, and also fails when the page is not committed at all.
  - The step's `::error::` annotation says to run `make api-types` and commit `docs/api.md`.
  - Because the job re-exports the contract from code first, it catches both of these:
    - an API change with no regeneration;
    - a hand edit to `openapi.json` or `api.md`.
  - We rejected a separate job, which would repeat the setup on one more runner.
- **D5. `make test` checks the committed page too.**
  - `test_the_committed_api_docs_match_the_committed_contract` renders the committed `docs/openapi.json` and compares the result with the committed `docs/api.md`. Drift fails locally before a push.
  - The frontend's input-limits test against `openapi.json` works the same way (ADR 0071 D6).
- **D6. No examples.** The page shows only what the contract states, so nothing is invented and nothing drifts. We rejected examples added to the request types and skeleton examples built from the schemas.
- **D7. The narrative stays in the README.**
  - The page's **Errors** section shows what the contract states:
    - the `ErrorResponse` fields;
    - its `code` values;
    - the operations that answer `429`.
  - It links the README's "Errors, limits and timeouts" section and ADRs 0071 and 0079 for what each code means, the limits, the timeouts and the rate-limit groups.
  - We rejected an intro in the FastAPI app's `description`, which would change the API code for prose.
- **D8. The untagged health routes are grouped under "Health".** Only `/health` and `/api/health` have no tag, so the generator files untagged operations there. The API does not change.
- **D9. Endpoints follow SPEC §10's flow.**
  - The order is health, sessions, plans, catalog, competitors, relations, models, evals.
  - A tag outside that list follows, alphabetically.
  - Within a tag, operations sort by path, then method.
  - Schemas are alphabetical.

## The page

- **Opening.** The page opens with the contract's title, a note that it is generated and must not be edited by hand, and the contract and OpenAPI versions.
- **Errors.** Described in D7.
- **Endpoints.** An index table links every operation. Then, per tag, each operation shows:
  - method and path, summary and description;
  - a parameters table: name, where it goes, type, required, constraints and description;
  - the request body;
  - a responses table: status, description, body and headers such as `Retry-After`.
- **Event streams.** An event-stream response names the schema of each event's `data`.
- **Schemas.** Each schema has its description and a fields table: type, required, constraints and description.
  - **Types.** Every named schema links to its own section. Types read as "X or null", "array of X" and "map of string to X".
  - **Constraints.** They use the contract's own keywords: `maxLength 2000`, `minimum 1`, one of the enum's values, the default, read-only.
  - **Special schemas.** An enum schema lists its values. A union says which field tells its members apart. A schema with no constraint says "Any JSON value".

## Consequences

- **In-flight tickets.** A ticket in flight when this lands (#157, #159, #71) must rebase, rerun `make api-types`, which rewrites `docs/api.md` with the contract, and commit the page. Until then its contract job and `make test` fail, naming the file.
- **Reviews.** The page is about 1,600 lines (60 KB). A contract change shows up as a readable diff in review, next to `openapi.json` and `schema.d.ts`.
- **Wording.** Descriptions come from the docstrings, route `description`s and pydantic field descriptions. A clearer page therefore means clearer descriptions in the code, not edits to the page.
