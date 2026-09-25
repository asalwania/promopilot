# Shared domain value types live in `promopilot.domain`

The vocabulary types that cross module boundaries (Region, Segment, Mechanism, Plan line, Promo plan, Planning request, Company policy) live in one logic-free module, `promopilot.domain`, as immutable pydantic models, and every other module imports them from there. SPEC §7.3 lists no such module; we added it because the oracle (E2) must score a promo plan before the optimiser (E6) or agents (E3/E8) exist, and letting each module define its own plan type would mean converters at every boundary and a real risk of the oracle scoring something subtly different from what the optimiser produced.

## Consequences

- `promopilot.domain` holds types and their validation rules only (e.g. a plan has at most one plan line per SKU per region; a plan line starts and ends inside the promo window). No arithmetic on outcomes, no I/O.
- Types are named from CONTEXT.md. A new cross-module concept gets its glossary entry first.
- It is the one module every other module may import, so it must stay small and stable; module-specific result types (e.g. an optimisation result, a simulation result) stay in their own modules.
