# Agents decide, tools compute, humans approve

LLM agents (context, planner, critic, explainer) handle understanding the brief, choosing which tools to call, weighing trade-offs and writing explanations; every number a user sees (demand, uplift, profit, margin, stock, simulation percentiles) comes from deterministic, tested Python modules (demand model, relations, optimiser, simulator, mechanism comparator), and a plan only becomes final after explicit human approval. We chose this over letting the LLM reason numerically because the D2 claim requires demonstrable reliability: LLM arithmetic is not reproducible or testable, whereas deterministic tools can be property-tested and scored against ground truth.

## Consequences

- `promopilot.agents` contains no business arithmetic; the explainer's text is checked by `check_numeric_grounding` against tool outputs, regenerating once and then falling back to a template explanation.
- The deterministic optimiser must still produce a plan when the LLM is unavailable (graceful degradation, SF-03).
- Tests never call a real LLM: `FakeProvider` (scripted) or `ReplayProvider` (recorded cassettes); live calls only under `@pytest.mark.live`.
- Approval is an interrupt in the agent graph, and approvals/rejections are persisted with an audit trail.
