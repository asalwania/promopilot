# The constraint checklist reads pass or fail from the revision's open violations; the not-selected list shows the optimiser's own top five; an infeasibility panel shows the shortfalls, binding constraints and relaxation, accepted in one click

E10 (#62) lets managers verify a plan at a glance (SPEC §11, F-01 AC3, AG-06). It needs:
- a constraint checklist with pass or fail for budget, minimum margin, stock, clearance and policy;
- the top 5 not-selected options with their reasons;
- for an infeasible request, the binding constraints and the proposed relaxation, with a one-click amend that applies it.

The read model already carries most of this on the plan revision:
- `open_issues`: every violation `validate_plan` finds on the chosen attempt, and its risk findings. The Critic stores them at its save point (ADR 0051);
- `not_selected`: up to five of the best options left out, one per SKU and region, best first, with their value, reasons and cannibalised SKUs (ADR 0038, ADR 0040);
- `clearance_shortfalls`, `policy_findings`, `binding_constraints` and `relaxation` (ADR 0040, ADR 0044).

What it does not carry is any "pass" value. There is no plan-level promo cost total and no blended margin, and the plan-time facts behind them are not stored.

SPEC, #12 and #62 leave open:
- where each checklist row's result comes from;
- how policy findings and risk findings fit;
- where the not-selected list comes from;
- when the panel shows, what it holds and where;
- how the one-click amend behaves;
- which journeys prove it without a new recording.

We chose these with the owner (D1–D8 on #62, every recommended option).

## Decisions

- **D1. A checklist row fails when one of its violations is open, and passes otherwise.** There is no backend change and no migration.
  - `constraintChecks` (`lib/constraints.ts`) maps each `ViolationCode` to one row:
    - **Budget**: `BUDGET`, `REGIONAL_BUDGET`;
    - **Minimum margin**: `MIN_MARGIN`, `MARGIN_FLOOR`;
    - **Stock**: `STOCK`;
    - **Clearance**: `CLEARANCE_TARGET`;
    - **Policy**: `MAX_DISCOUNT`, `BELOW_COST`, `WINDOW`, `MAX_SKUS`, `KVI_TOLERANCE`, `DUPLICATE_LINE`.

    The map is typed over every code, so a new code does not compile until it has a row.
  - **Clearance** also fails on any `clearance_shortfalls`. It is **Not set** when the brief has no clearance target and nothing fails.
  - A failed row lists `validate_plan`'s own messages, which already state the actual value and the limit. An infeasible revision whose shortfalls have no violation of their own lists each shortfall instead.
  - A passed row names the limit it was checked against, taken from the planning request, for example "Within the marketing budget of ₹2 lakh". Without a brief minimum margin, it names the company-policy margin floor without a number, since the read model has no floor value.
  - Numbers name `validate_plan` (`SOURCES.checks`). Mapping codes to rows is a lookup: the UI computes nothing.
  - We rejected a stored `constraint_checks` field with the actual value per constraint. It would need migration 0015, a guardrails function and new API types. We also rejected computing the promo cost total at read time, which still leaves no margin.
  - A revision planned before E8 has no open issues stored, so it reads as all-pass. No such session is in the demo.
- **D2. Policy findings are notes on the Policy row**, for example "Policy kept: the brief's minimum margin of 10.0% is below the company-policy floor of 15.0%; the floor applies". They do not fail it, because planning kept the policy.
  - Risk findings (heavy cannibalisation, stock-out risk, over-concentration) stay out: they are not constraints.
- **D3. The not-selected list is the revision's `not_selected`, in its order.**
  - A "Not selected" card shows, for each option:
    - its SKU, region, mechanism (with "+ partner" for a bundle), depth, start, duration and segment;
    - its value alone (`formatMoney`, naming `run_optimizer`, `SOURCES.notSelected`);
    - its reasons.
  - All 11 `NotSelectedReason` codes have a label. "Cannibalises" names the plan lines' SKUs it loses too much with.
  - With no entries the card says "No worthwhile option was left out."
  - We rejected splitting the list across the region tabs, which breaks a top five ranked across regions.
- **D4. The infeasibility panel shows whenever the revision is `INFEASIBLE` or carries a relaxation.** A relaxation without `INFEASIBLE` is ADR 0044's timeout: `FEASIBLE`, with an unproven relaxation. The panel holds:
  - its title:
    - "Infeasible: no plan reaches every clearance target within the brief's constraints.";
    - or "Not proven feasible: the plan misses a clearance target, and the solver ran out of time before settling whether any plan reaches it.";
  - a "Clearance shortfalls" table: SKU, region, target, expected sell-through and units short;
  - the binding constraints with evidence `infeasible`, each at the brief's value;
  - a "Proposed relaxation" table: constraint, brief value, relaxed to ("Dropped" or "Off" when null), change as a share, and what policy allows;
  - notes:
    - "Company policy binds…" when `policy_binds` is true;
    - "Not proven smallest…" when `proven` is false.

  Relaxation values show to a basis point (`formatBasisPoints`), and a budget's tooltip gives it to the paisa. Every number names `relax_constraints` (`SOURCES.relaxation`), the tool that returns exactly these fields (ADR 0044).
- **D5. The panel replaces the plan card's one-line infeasible alert.** The checklist and the not-selected list are two cards after the plan card, before the audit trail.
  - #64's review card keeps its own note that an infeasible plan can't be approved, and the panel does not repeat it.
- **D6. Accepting is one click, with no confirmation.**
  - "Accept the relaxation and re-plan" calls `actions.amend({ acceptRelaxation: true })` (ADR 0066). The server writes the amendment's text from the relaxation (ADR 0052 D7), so the UI never composes it.
  - Re-planning keeps the accepted revision, so nothing is lost.
  - The button shows only while the session is `awaiting_approval` or `rejected` (ADR 0052 D1). It is disabled while the request is pending, and a failure shows its reason next to it.
  - Once accepted, the session is `planning`, and #64's note shows the relaxation's amendment text over the revision it amends. The panel stays, without its button.
- **D7. The journeys use existing recordings.**
  - The `e2e` plan journey also checks the checklist's five rows and the not-selected card.
  - The `demo` amend journey checks revision 1's infeasibility panel before it amends. That covers the binding SKU0006 clearance target, the relaxation row with its `relax_constraints` tooltip, and the accept button. It also checks the checklist's failing Clearance row. It adds no planning run.
  - It does not click accept: no cassette records that round. A `sessions.json` step that accepts the relaxation and then approves, plus its recording, is a separate follow-up.
- **D8. Names.** The components are `ConstraintChecklist`, `NotSelectedList` and `InfeasibilityPanel` (with `needsRelaxation`). The lib has `constraintChecks`, `constraintLabel` and `formatConstraintValue` in `lib/constraints.ts`, and `formatBasisPoints` in `lib/format.ts`. `SOURCES` gains `checks`, `notSelected` and `relaxation`.

## Consequences

- There is no backend, API contract or migration change. The frontend reads fields that were already typed.
- The checklist is only as complete as the stored open issues. A later ticket may store `validate_plan`'s plan-level actuals so that passed rows show them too.
- Vitest covers:
  - the checklist from fixtures: all pass, four failing, the brief's limits, policy notes, shortfalls;
  - the not-selected list: columns, every reason's label, the empty state;
  - the panel: infeasible, policy binds, a dropped target and a tolerance turned off, the timeout, one-click accept, a failure, no button;
  - `SessionDetails`, whose accept calls `amend({ acceptRelaxation: true })`;
  - `formatBasisPoints`.
- Follow-up: record the demo's accept-relaxation and approve steps (a new `sessions.json` step type), so a journey can click accept and approve the relaxed plan.
