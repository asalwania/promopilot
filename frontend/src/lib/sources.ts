// Which deterministic tool each number in the plan area comes from (SPEC §11:
// every number names its source tool). Provenance is fixed per read-model field
// by the architecture, not per session, so it lives here once instead of in
// every response (ADR 0060, which amends #12's "the read model carries it").
export const SOURCES = {
  // The optimiser's decision for the line: depth, start week and duration.
  decision: "run_optimizer",
  // The line's own expected numbers, predicted for every candidate option.
  lineEstimate: "generate_candidates",
  // The line's units by segment, from the same demand model.
  segments: "estimate_demand",
  // The SKUs the line moves, from the relations model on the candidate options.
  crossEffects: "generate_candidates",
  // Every P10–P90 range and stock-out risk: the Monte Carlo simulation.
  simulation: "simulate_plan",
  // The drawer's alternatives for the line's SKU and region.
  mechanisms: "compare_mechanisms",
  // Competitor prices and undercut KVIs at the request's as-of week.
  competitorGaps: "get_competitor_gaps",
  // The constraint checklist: the Critic's hard-constraint check (ADR 0067).
  checks: "validate_plan",
  // The best options left out, and why (F-01 AC3).
  notSelected: "run_optimizer",
  // An infeasible request's shortfalls, binding constraints and relaxation (ADR 0044).
  relaxation: "relax_constraints",
} as const;

export type Source = (typeof SOURCES)[keyof typeof SOURCES];
