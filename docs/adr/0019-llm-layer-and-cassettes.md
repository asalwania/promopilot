# The LLM layer is async, and cassettes are one JSON file per provider-independent request hash

SPEC §9.6 asks for an `LLMProvider` protocol with `complete_structured(schema, messages)`, a scripted `FakeProvider`, and a `ReplayProvider` that answers from cassettes keyed by a request hash, so CI and `make demo` run with no API key. SPEC does not fix the call style, the cassette layout or what the hash covers. We chose these with the owner in E3 (#22):

- **Async.** `complete_structured` is a coroutine. Planning sessions run as background tasks in the FastAPI process, LangGraph nodes can be async, and the OpenAI SDK has an async client, so a sync interface would have to be offloaded to threads everywhere.
- **One JSON file per request.** A cassette is `LLM_CASSETTE_DIR/<hash>.json` (default `backend/cassettes/`). It holds the hash, the schema name, the request content and the parsed response. Separate files keep diffs readable and avoid merge conflicts when several scenarios are recorded.
- **The hash covers only provider-independent content.** It is the SHA-256 of canonical JSON (sorted keys, no whitespace) of the schema's JSON Schema, the messages (role and content) and the temperature. The provider and model ID are left out, so a cassette recorded with OpenAI replays when the model or provider changes. A changed prompt or schema changes the hash, and replay then fails loudly with `CassetteMissError`, which names the hash.
- **Recording is a wrapper.** `RecordingProvider(inner, cassette_dir)` calls a live provider and writes the cassette from the request content and the parsed response only. Transport details such as headers and the API key never reach it.
- **`build_provider(settings)`** picks the provider from `LLM_PROVIDER`: `replay` (the default) or `openai` (needs `OPENAI_API_KEY` and `OPENAI_MODEL`). `anthropic` fails with a pointer to E8. `fake` fails too, because a `FakeProvider` needs a script and is built directly in tests.
- **Every OpenAI failure is an `LLMError`**: API errors, unparseable answers and refusals. Callers handle a single exception type. Retries and fallback arrive in E8.

## Consequences

- Any prompt or schema change needs `make record-cassettes` (E3 #25) before replay works again. That is intended: a stale cassette must never answer silently.
- Upgrading pydantic could change a schema's generated JSON Schema, and so every hash. Cross-process stability is tested, but not stability across library versions.
- openai 3.x speaks HTTP through `httpx2`, not `httpx`. OpenAI tests mock at that transport, and no test calls a real LLM.
