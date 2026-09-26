# The Docker stack always replays cassettes baked into the api image, and `make record-cassettes` replaces them all or none

E3 (#25) proves the walking skeleton runs with no API key: Playwright types a brief on the composed stack and sees a plan. SPEC asks for committed cassettes recorded by `make record-cassettes` with live keys, and a no-key e2e run. It does not say where the recorded briefs live, how stale cassettes are handled, how the stack finds cassettes, or how CI gets data. We chose these with the owner:

- **Briefs live in `backend/cassettes/briefs.json`.** It is a JSON list of briefs, next to the cassettes recorded from them. The recorder plans each one, and the Playwright journey types the first. The e2e brief is a Diwali promotion for Snacks and Beverages in North and West with a ₹2 lakh budget.
- **Recording replaces everything or nothing.** `record_cassettes` (in `promopilot.agents`) runs `plan_session` for each brief through a `RecordingProvider` into a scratch directory. If any brief fails to reach a plan (a `BriefError` or `LLMError`), nothing changes and the run exits non-zero. If all succeed, every hash-named cassette is replaced, so no stale cassette survives. Other files, such as `briefs.json`, are kept. `python -m promopilot.cassettes` is the CLI, and it reads the data loaded in Postgres (`make data` first).
- **Recording needs a model that accepts `temperature=0`.** ADR 0019 fixes structured calls at temperature 0, and the temperature is part of the request hash. The `gpt-5` reasoning models reject any temperature but 1, so cassettes are recorded with `OPENAI_MODEL=gpt-4.1-mini`.
- **The Docker stack always replays.** Compose sets `LLM_PROVIDER=replay` and passes no key, and the api image copies `backend/cassettes/`. A live provider in `.env` affects only `make dev` and `make record-cassettes`, never the stack a judge runs.
- **CI loads the full seed-42 world inside the api container.** After `docker compose up`, `docker compose exec api python -m promopilot.datagen --out /tmp/data --load` generates and loads the default world in about 45 seconds. That is the world `make data` builds and the cassettes were recorded against. We rejected a smaller CI world: it would plan differently from the demo and add a second config. The ground truth is written inside the container and discarded with it.
- **The backend job checks the committed cassettes.** A unit test replays every brief in `briefs.json` over the in-memory default world. A prompt, schema or calendar change therefore fails fast in the backend job, not only in the images job.

## Consequences

- After changing a prompt, a schema or the default world, run `make data` and `make record-cassettes`, commit the cassettes, and rebuild the image (`make up`).
- Cassettes ship inside the api image, so `make demo` (E11) needs no key and no volume.
- E9 eval scenarios and E11's example briefs can add briefs to `briefs.json` or grow the recorder's input. They need no new mechanism.
