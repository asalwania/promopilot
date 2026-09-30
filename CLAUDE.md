# CLAUDE.md
Project: PromoPilot — agentic retail promotion planner (see SPEC.md).

## Commands
- make setup | make data | make train | make dev | make test | make eval | make demo | make screenshots | make lint | make typecheck | make api-types | make tool-docs

## Rules
- SPEC.md is the source of truth. If something is ambiguous, ask; record decisions in docs/adr/.
- TDD always: failing test first, then minimal code, then refactor.
- Never call a real LLM in tests. Use FakeProvider or ReplayProvider.
- Only promopilot.evals and promopilot.datagen may touch data/ground_truth/.
- The LLM never computes numbers; all numbers come from deterministic tools.
- Every stochastic function takes an explicit seed.
- Keep modules deep with small interfaces; no cross-module private imports.
- Conventional Commits; one ticket per PR; CI must be green before merge.
- Never commit secrets. Update .env.example when adding config.
- Update README/docs when behaviour or commands change.

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues on `asalwania/promopilot` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
