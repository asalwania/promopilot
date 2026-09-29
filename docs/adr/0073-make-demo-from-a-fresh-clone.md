# `make demo` prepares the data and models in an init step, replays unless `.env` holds a key, and explains a brief outside the recordings instead of failing it

E11's #72 makes the judge's first run safe. On a fresh clone with only Docker, `make demo` must bring up the whole app with the seed-42 data, trained models and the example briefs, and need no API key. The first start should be ready in about 5 minutes with its progress visible, and later starts should reuse the data and models. A brief with no cassette should show the demo's limits, not an error. CI must prove all of this from a clean checkout.

SPEC §15 E11, spec #13 and #72 leave open:

- how the demo profile and its init step are shaped, and how "skip work already done" is detected;
- how "replay unless a key is present" is switched, and how the UI shows the mode;
- what a cassette miss does, given that it already degrades (ADR 0027, 0049, 0050, 0053);
- how the Docker stack ships an eval report, so `/evals` is not empty (ADR 0069 D7, ADR 0072);
- the CI job's shape, the time to ready, Windows and Linux, and the docs.

We chose these with the owner on #72 (D1–D9, every recommended option).

## Decisions

- **D1. An `init` service in a `demo` profile.**
  - `docker-compose.yml` gains `init`, built from the api's Dockerfile, which runs `python -m promopilot.demo` with the api's database URL and the `model-artifacts` volume.
  - The api depends on it with `condition: service_completed_successfully` and `required: false`. So `make up`, which does not enable the profile, is unchanged, and `docker compose --profile demo up --build` works without make.
  - We rejected an overlay compose file (two files to keep in step) and an init step outside a profile (it would slow every `make up`).
- **D2. The init step reads the real state and skips what is done.**
  - `promopilot.demo.prepare` runs two steps:
    1. **Data.** It migrates first, which is idempotent. If no sales history is loaded, it generates the seed-42 world with the default config into a temporary folder, as `make data` does, and loads it. The folder, ground truth included, is deleted with it.
    2. **Models.** It trains and registers demand, then relations, as `make train` does, unless three things hold for each kind: the latest version is registered, its artifact is on the volume, and it was trained as of the loaded data's first future week.
  - Each step prints what it does, an estimate and then its time, or says it was skipped. A failure exits 1 with the reason, so the api never starts on a half-prepared stack.
  - No marker file is used: it could disagree with the Postgres or model volume when only one of them is removed.
  - A change to the generator after a `git pull` is not detected. `make demo-reset` starts over.
- **D3. `LLM_PROVIDER=auto`, only in the demo.**
  - `Settings` resolves `auto` before anything reads it:
    - `openai` when `OPENAI_API_KEY` is set;
    - otherwise `anthropic` when `ANTHROPIC_API_KEY` is set;
    - otherwise `replay`.
  - A keyed provider with no model uses the recorded one: `gpt-4.1-mini`, or `claude-sonnet-5`. So a key alone is enough, and the other keyed provider is still the fallback (ADR 0027).
  - Compose passes the keys from `.env` into the api. It also sets `LLM_PROVIDER: ${STACK_LLM_PROVIDER:-replay}`, and `make demo` sets `STACK_LLM_PROVIDER=auto`. So `make up` still always replays (ADR 0022), and a key in `.env` never makes it spend money.
  - We rejected `auto` for `make up` too, and a Makefile that greps `.env`: shell logic that can't be tested, which the make-free command would lose.
  - With a key, the live provider answers everything. We rejected answering from the cassettes first and going live only on a miss: a new provider wrapper that mixes recorded and live answers in one session.
- **D4. `/health` says which LLM answers.**
  - `HealthResponse.llm` is `LLMStatus {mode: replay | live, provider, model}`, built from the settings. `model` is null when replaying.
  - The home page shows a badge above the examples. It reads **Demo mode**, "replaying recorded sessions, no API key", or **Live LLM** with the provider and model.
  - `make demo` prints the same once the stack is ready.
  - We rejected a new `GET /api/demo`: one more endpoint for a fact `/health` can carry.
- **D5. A brief outside the recordings plans without the LLM, with a notice. It is not refused.**
  - `SessionResponse.demo_recording` is computed on read, with no migration:
    - null with a live LLM;
    - `recorded` while the session's brief, clarification answers and amendments so far are those of a recorded session script;
    - `not_in_demo_recordings` once they are not.
  - "Those of a recorded script" means:
    - the brief is word for word the script's;
    - every answer is one the script gives, under its question id;
    - the amendments are, in order, the start of the manifest's recorded amendment texts, which include the text an accepted relaxation wrote (ADR 0070 D5).
  - `promopilot.api.demo.DemoRecordings` reads them from the cassette manifest once at startup. The API builds it only when replaying.
  - **This deviates from #72's and spec #13's literal "returns a typed not-in-demo-recordings error".** The typed code `not_in_demo_recordings` is on the session, not on an error response.
    - Since ADR 0027, 0049, 0050 and 0053, a miss already degrades. The Context agent reads by rules, the planner runs the default sequence and the Explainer uses its template. So such a session still ends with a plan.
    - Refusing would make the constraint form useless without a key, since any constraint changes the brief (ADR 0058 D3). It would also contradict ADR 0058 D8's note, and hide the fault tolerance (SF-03) the demo can show.
    - The story behind the criterion ("a clear message … instead of seeing an error") holds. The `ErrorCode` enum is unchanged.
  - **The UI explains the demo's limits in an info note titled "Not in the demo recordings", never in the error component.**
    - In replay mode the composer shows it as soon as the text is not an example brief, before **Plan it**.
    - The session page shows it under the status while `demo_recording` is `not_in_demo_recordings`.
    - Both say the session plans without the language model (rules read the brief, the default sequence plans and a template explains), and offer two ways out: pick an example brief, or set `OPENAI_API_KEY` in `.env` and run `make demo` again.
  - We rejected a 422 refusal, and a refusal with an "allow unrecorded" override flag, which grows the contract most.
- **D6. The api image bakes in the recorded full eval run.**
  - `backend/evals/published/latest.json` and `latest.md` are a copy of #58's live full run on 2026-09-29: 32 scenarios, provider "openai (recording)". It was checked for keys and paths before it was committed.
  - The Dockerfile copies the folder, and the compose api sets `EVAL_REPORT_DIR=evals/published` in both profiles. So `/evals` shows a report on `make demo` and `make up`, and `make dev` still serves the host's own `make eval` runs.
  - A unit test serves it through `GET /api/evals/latest`. A change to the report's shape then fails the backend job until the copy is refreshed from a new run.
  - This supersedes ADR 0069 D7's "the Docker stack mounts no report folder, so it answers 404" and ADR 0072's Docker empty state.
  - We rejected generating a report in the init step (6+ minutes of CPU on a judge's laptop) and a bind mount (still empty on a fresh clone, and ADR 0069 D7's root-owned folder).
- **D7. CI's `demo` job replaces the `images` job.** From a clean checkout with no key it:
  - runs `make demo`;
  - checks that `/health` is `ok` and replaying, and that `/api/evals/latest` answers;
  - replays every recorded session in the api container (`cassettes --check`, ADR 0054 D5);
  - runs the Playwright journeys, including a new `demo-limits.spec.ts` and `evals.spec.ts`, which now checks the populated dashboard;
  - runs `make demo` again and checks that both init steps say "skipped";
  - tears down with `make demo-reset`.

  The smoke eval stays in the parallel `eval-smoke` job, because the api image carries no eval harness (ADR 0069 D6). The workflow, rather than the one job, therefore covers "runs the smoke eval". We rejected keeping `images` beside `demo`, which would double the build and the Playwright run, and a serial smoke eval inside `demo` (about 20 minutes rather than 13).
- **D8. No prebuilt images, and the URL is printed rather than opened.**
  - `make demo` does five things:
    1. builds;
    2. starts Postgres;
    3. runs `init` in the foreground, so its progress shows;
    4. starts the api and web and waits for their health checks;
    5. prints the LLM mode and "PromoPilot is ready: http://localhost:3000".
  - `make demo-down` stops the stack and keeps its volumes. `make demo-reset` removes them.
  - `COMPOSE` can be overridden, for example to `docker compose -p pp-test`, to run a second isolated stack.
  - make is not "only Docker": on Windows it needs Git Bash. The README therefore also gives the make-free `docker compose --profile demo up --build` for PowerShell, with `STACK_LLM_PROVIDER=auto` set for live mode.
  - The init step is Python, so it runs the same on Windows and Linux with no line-ending risk.
  - We rejected images published to GHCR, which save about a minute and a half but need registry permissions and tag drift handling, and opening a browser, which is platform-specific.
- **D9. Docs.**
  - The README opens with "Try it: `make demo`".
  - `.env.example` documents `auto` and `STACK_LLM_PROVIDER`.
  - CONTEXT.md gains *Demo mode* and *Demo recordings*.

## Consequences

- **New public names:**
  - `promopilot.demo` (`prepare`, `PostgresDemo`, `python -m promopilot.demo`);
  - `promopilot.api.demo` (`DemoRecording`, `DemoRecordings`);
  - `LLMStatus`, with `create_app(llm=...)` and `SessionService(recordings=...)`;
  - `Settings` accepts `LLM_PROVIDER=auto`.
- **API contract:** `HealthResponse.llm` and `SessionResponse.demo_recording`. There is no migration.
- **New configuration:** `STACK_LLM_PROVIDER` (Compose only) and the `auto` value.
- **This amends:**
  - ADR 0022 ("the Docker stack always replays"): it still does under `make up`, but not under `make demo` with a key;
  - ADR 0058 D8: the composer's note now appears only when replaying and the text is not an example;
  - ADR 0069 D7 and ADR 0072: the Docker stack serves the baked report.
- The baked report ages with the product. After a report-shape change, or a new full recorded run, copy `backend/evals/reports/latest.json` and `latest.md` into `backend/evals/published/`.
