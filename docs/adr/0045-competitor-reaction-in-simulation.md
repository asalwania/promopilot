# A competitor reaction is drawn per plan line and run from its own seeded stream, and a match puts the competitor price index back where it was before the promotion

E7 (#41) adds the competitor-reaction scenario to the Monte Carlo simulator (SPEC §9.5, F-09 AC2, user stories 7 and 8 on #9). It lets a manager stress-test a plan against a price war. The owner kept it in scope although SPEC §15 lists it as cut-line item 3, as an optional parameter that changes no interface. ADR 0042 already fixed where it acts: a match adjusts each run's competitor term γ · (log(cp / p) − log r) (ADR 0024). ADR 0043 reserved `competitor_reaction` on the re-simulate endpoint as a null-only field for this ticket to widen. SPEC and the issue left six questions open. We chose these with the owner (D1–D6 on #41):

- **D1. The scenario is `{"match_probability": p}`, with 0 ≤ p ≤ 1 and no other field.** It is the domain value type `CompetitorReaction`, and the simulator, the `simulate_plan` tool and `POST /api/plans/{id}/simulate` all take it. A later field, such as a partial match, can be added without renaming anything.
  - We rejected a bare number, which cannot grow. We also rejected adding a match share now, which nothing asks for.
- **D2. Each plan line draws its own reaction in each run, independently of the other lines.** A line is one SKU in one region, which is also the grain of a competitor price, so the competitor reacts to each promotion on its own. With p between 0 and 1, a plan's totals mix matched and unmatched lines.
  - We rejected one draw per run for the whole plan (an all-or-nothing price war, which makes plan totals bimodal) and one draw per region per run.
- **D3. A match is full, and at the price each row pays.** A matched competitor cuts its price by the share our customers get off the base price: cp' = cp × p / base price. The row's competitor term then becomes log(cp / base price) − log r, so the competitor price index returns to its level before the promotion. The promotion loses the demand it gained on the competitor, while its own-price effect (β) and mechanism effect (μ) stay.
  - The row's own price carries the mechanism: BOGO counts as 50% off, FIXED_PRICE as its charm price, and a BUNDLE's partner at its own discount (ADR 0005, ADR 0015). Rows that pay the base price, such as the segments a segment-only offer does not target, are unchanged.
  - We rejected cutting the competitor's single regional price by the line's depth for every segment, which would push untargeted segments below their baseline. We also rejected a price-level match (cp' = min(cp, our promo price)).
- **D4. The competitor may react to every plan line.** The effect scales with each SKU's sampled γ. "Undercut-sensitive" SKUs are therefore those with a positive γ: they sell fewer units when matched, and a SKU with γ = 0 is unchanged.
  - We rejected limiting the reaction to KVI lines. ADR 0031 calls only a KVI undercut, but the demand model gives every SKU a competitor sensitivity, and a KVI-only rule would add a second definition of who reacts.
- **D5. The reaction draws come from their own generator of the same seed.** The terms and the demand noise still come from `default_rng(seed)`, in the same order (ADR 0042). The reaction comes from `default_rng([seed, 1])`, created only when the scenario is given. This amends ADR 0042's "one generator" to "one seed". Three things follow:
  - Omitting the scenario gives bit-for-bit the results from before this ticket, and a test pins them.
  - p = 0 gives the same results as omitting it.
  - p = 0 and p = 1 share every term and noise draw, so their difference is the reaction alone.
  - We rejected drawing the reactions from the main generator right after the terms. Omitting the scenario would still be unchanged, but p = 0 would not be, and comparing p = 0 with p = 1 would pick up noise.
- **D6. The session's own simulation never uses it, and a re-simulation stores it.**
  - `OptimisingPlanner` still simulates plan revision 1 with no reaction.
  - `simulate_plan` takes an optional `competitor_reaction` (none by default), so E8's planner agent can ask for a stress test.
  - `POST /api/plans/{id}/simulate` stores its result in place of the old one, as ADR 0043 decided. `PlanSimulation.competitor_reaction` records the scenario, so the session read model and the UI can label a stress-tested simulation.
  - The field lives in the existing `plan_revisions.simulation` JSONB column, so no migration is needed. Simulations stored before this ticket read back with none.
  - We rejected returning a scenario's result without storing it, which would change ADR 0043. We also rejected a `SIMULATION_COMPETITOR_REACTION` setting that applies it by default.

The details below follow from those choices:

- **Where γ is.** `promopilot.models.demand.COMPETITOR_TERM` names the competitor term's column in `ResponseRows.design`. The simulator subtracts the sampled γ × log(base price / price) from a matched row's log mean. A demand model without that column is simulated as if the competitor never reacted.
- **Validation.** p outside 0–1, a missing p, an unknown field or a bare number is `invalid_input` from the tool and `422` from the endpoint.
- **The ranges stay ordered.** The P10 ≤ P50 ≤ P90 property test now also draws a reaction for some examples.

## Consequences

- On the seed-42 demo brief (35 lines, every SKU with γ > 0, 2 of them KVIs), 1,000 runs give these plan P10 / P50 / P90:

  | Match probability | Units | Gross profit | Promo spend |
  |---|---|---|---|
  | none, or 0 | 12,478 / 12,866 / 13,269 | ₹445,224 / ₹463,112 / ₹481,098 | ₹194,359 / ₹200,369 / ₹205,895 |
  | 0.5 | 11,842 / 12,287 / 12,764 | ₹435,447 / ₹453,258 / ₹472,128 | ₹186,113 / ₹192,462 / ₹199,368 |
  | 1 | 11,339 / 11,659 / 12,034 | ₹424,520 / ₹441,811 / ₹459,765 | ₹179,005 / ₹184,125 / ₹189,803 |

  - Without a reaction, the figures are ADR 0042's, unchanged.
  - At p = 1, P50 units fall on 33 of 35 lines. The other two sit at their stock cap at P50 either way. The hardest hit lose about a fifth: a 25%-off line with γ ≈ 0.9 falls from 1,066 to 822, and the KVI on a 10% charm price with γ ≈ 1.2 falls by about 21% in both regions.
  - Fewer units also mean less discount funding and fewer stock-outs: North's stock-out probability falls from 0.27 to 0.16, and West's from 0.12 to 0.08.
- Simulating the demo plan at 1,000 runs takes about 0.6 s without a reaction and about 1.0 s with one, a small share of SPEC's 10 s. A 100-line plan takes about 1.2 s and 1.3 s. The speed test is unchanged.
- The UI (E10) can offer "re-run with competitor reaction" on the plan on screen and label the stored result from `simulation.competitor_reaction`. The critic (E8) can compare a plan's P10 profit under a reaction with its expected profit.
- A stored stress-tested simulation replaces the plain one until the next re-simulation without a reaction, as any re-simulation does (ADR 0043).
