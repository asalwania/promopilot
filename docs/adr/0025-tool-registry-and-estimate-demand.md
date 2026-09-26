# Tools are typed async handlers that return typed errors, and `estimate_demand` resolves the latest model on every call

E4 (#28) adds `promopilot.agents.tools`, the single seam through which agents reach deterministic computation (ADR 0002), and `estimate_demand` as its first tool. SPEC §9.6 asks for typed JSON-schema tools, and the ticket asks for pure handlers over injected dependencies and typed errors for invalid input. The spec does not fix the handler shape, how the model is injected, the tool's input and output, or the error design. We chose these with the owner:

- **A tool is a pydantic input model, a pydantic output model and an async handler.**
  - Their JSON schemas are what the LLM sees.
  - Dependencies are bound when the tool is built, never passed by the LLM.
  - `ToolRegistry.specs()` lists each tool's name, description, input schema and output schema.
  - `await ToolRegistry.call(name, arguments)` runs one.
  - Handlers are async because the data tools that follow (#83, E5) read the async as-of-week repositories.
  - We rejected sync handlers over preloaded data, which would force every data tool to load its tables up front.
- **`call` returns `ToolOk | ToolError(code, message, details)` and never raises for a bad call.**
  - The codes are `unknown_tool`, `invalid_input` and `model_unavailable`.
  - `details` locates each schema violation, e.g. `options.0.depth_pct`.
  - A handler signals a schema-valid call it cannot answer by raising `ToolCallError`. For `estimate_demand` these are an unknown SKU or region, a start before the as-of week, or weeks past the calendar: `DemandModel.predict` raises `ValueError` for exactly these.
  - The planner can hand the error back to the LLM to correct its call (SF-03). A bug in a handler still raises.
  - We rejected raising typed exceptions for the caller to convert, which would put the same conversion in every caller.
- **`estimate_demand` is given the `LatestModel[DemandModel]` handle and resolves it on every call.**
  - A model registered after the API started, or swapped in by a retrain (#29), is used without rebuilding the registry.
  - With no model, the call returns `model_unavailable`.
  - The output names the model's id, version and as-of week, so every plan can be traced to the model that produced its numbers (SF-02).
  - The API builds the registry at startup and keeps it on `app.state.tools`; no endpoint exposes it.
  - We rejected injecting a model snapshot, which would need the registry rebuilt on every retrain.
- **The input is 1 to 200 plan lines plus optional competitor price overrides.**
  - Each override is a region, a SKU and a price, at most one per region and SKU. Other competitor prices are the last known (ADR 0024).
  - Company policy is bound when the tool is built; the LLM cannot set it.
  - Extra fields are rejected.
- **The output is `predict`'s numbers, unrounded.**
  - Each estimate echoes its plan line, gives the 10 `Prediction` columns and has a per-segment table of units, std and baseline.
  - Rounding is left to the numeric-grounding tolerance (E8), so the numbers an explanation quotes can be traced exactly.
- **Prediction runs in a worker thread** (`asyncio.to_thread`), so a 200-option call does not block the event loop.

## Consequences

- E5–E8 tools follow this shape: pydantic input and output, an async handler, and `ToolCallError` for calls they cannot answer.
- The LLM layer's `complete_with_tools` (E8) builds its provider tool definitions from `specs()`.
- Schema validity is checked through pydantic: the listed schemas are generated from the same models that parse the input and build the output. No JSON Schema validator is added.
