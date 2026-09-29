# Strong substitutes are never promoted together: a hard, always-on company-policy rule on the relations model's estimated θ, at most one option per pair, region, week and segment

#58's first full eval run found two of the three heavy-cannibalisation scenarios promoting strong substitutes together, failing `no_strong_substitutes_together` (ADR 0065):

- `cannibal-bakery-diwali-2026` promoted SKU0194 and SKU0195 (true θ 0.64) together in North and West;
- `cannibal-personal-care-offseason` promoted SKU0085/SKU0087 (θ 0.73) and SKU0077/SKU0078 (θ 0.69) together in North.

The optimiser only charged such a pair its pairwise cannibalisation (ADR 0033). When both lines were worth more than what they lose together, it kept both. #158 adds a hard guard. The ticket leaves open:

- what "strong" is, when the model has estimates and the eval has the truth;
- what "together" is;
- whether the rule is always on or a planner or brief option;
- whether it is a hard constraint or a penalty;
- how it shows in the binding constraints, the not-selected reasons, `validate_plan` and the relaxation.

We chose these with the owner at #158's decision gate (every recommended option).

## Decisions

- **D1. Strong: a pair the relations model detects as substitutes, with an estimated θ of at least `CompanyPolicy.strong_substitute_min_theta = 0.35`.**
  - A detected substitute has a Benjamini–Hochberg q below 0.05 and a θ of at least 0.1 (ADR 0013). The model fits one symmetric θ per pair (ADR 0029), so "directed or the larger of both" does not arise: the eval takes the larger of the generator's two directed θ, and the model has one.
  - The guard reads the model's estimates only (`OptionFacts.substitutes`, served by `FittedOptionFacts` from the relations model). Only `promopilot.evals` and `promopilot.datagen` touch the ground truth.
  - Why 0.35 and not the eval's 0.5: the model's θ runs about a fifth below the truth. On the seed-42 world at week 104, estimated over true θ has a median of 0.82. Examples:

    | Pair | True θ | Estimated θ |
    |---|---|---|
    | SKU0194/SKU0195 | 0.64 | 0.54 |
    | SKU0085/SKU0087 | 0.73 | 0.58 (0.51 at week 82) |
    | SKU0077/SKU0078 | 0.69 | 0.64 |
    | SKU0195/SKU0198 | 0.79 | 0.44 |

  - Of the world's 80 true pairs with θ at least 0.5, an estimated-θ threshold covers:

    | Threshold | Detected pairs flagged | True-strong pairs covered | Others flagged |
    |---|---|---|---|
    | 0.5 | 50 | 49 | 1 |
    | 0.4 | 75 | 71 | 4 |
    | 0.35 | 80 | 73 | 7 |

    Every other pair flagged is a true substitute with true θ between 0.3 and 0.5; no non-substitute is flagged. In the three heavy-cannibalisation scopes, the least estimated θ of a true-strong pair is 0.37 (Bakery, week 104), 0.38 (Frozen, week 62) and 0.41 (Personal Care, week 82). 0.35 covers them all.
  - This calibration was done once, offline, reading the ground truth in a scratch analysis. No code reads it.
  - We rejected 0.5, the eval's number: it leaves about 40% of the truly strong pairs unguarded, and the optimiser would shift onto one of them. We rejected 0.4, which misses SKU0193/SKU0196 (0.37) and SKU0160/SKU0164 (0.38).
  - It lives in `CompanyPolicy`, as a company rule, rather than in an env var or `RelationsConfig` (which is versioned with the model). No prompt carries the policy object, so the field changes no LLM request.
- **D2. Together: the eval's own definition.**
  - Two plan lines run together when they are in one region, with a promo week and a target segment in common. All customers shares every segment, and a BUNDLE promotes its partner too (`guardrails.run_together`, which the pairwise term's `_together` now uses as well).
  - A BUNDLE whose anchor and partner are a strong pair is not eligible. Partners are detected complements today, so this is a safeguard.
  - Encoding: for each strong pair, region, week and real segment, `add_at_most_one` over the eligible options that cover that cell with either SKU. Options of one SKU in one region already exclude each other, so this forbids exactly the pairs that run together. It lets the solver drop one SKU, or shift it to other weeks or another exclusive segment.
  - We rejected pairwise `x_i + x_j ≤ 1` rows (the same result, many more rows) and "same region" alone, which blocks staggered or segment-exclusive plans the eval allows.
- **D3. Always on.**
  - We rejected a tighten-only brief field on `PlanningRequest`: the request is in every planner tool's input schema, so every cassette (74 app, 308 eval) would miss, and the planner could loosen it.
  - We rejected a planner argument on `run_optimizer`: the tool schema changes, so every planner cassette misses.
- **D4. A hard constraint, not a penalty.** The eval property is pass or fail, and a very large penalty needs calibrating and could still lose to a big value. The objective stays in real rupees, so the binding gains and the explanations stay honest.
- **D5. One binding constraint, `ConstraintKind.STRONG_SUBSTITUTES`** (`strong_substitutes`).
  - Its source is `company_policy` and its limit is the θ threshold. The web app reads "Strong substitutes kept apart: θ ≥ 0.35", and the Explainer reads "the rule against promoting strong substitutes together at θ 0.35".
  - The existing analysis settles it (ADR 0038):
    - it can bind only when some group holds options of both SKUs;
    - the swap check and `_evaluate` respect the rule for every other constraint, so a swap that breaks the rule proves nothing about the budget;
    - a re-solve without it drops every group at once and asks for a better plan that breaks one.
  - It is reported only when it binds, like every other constraint.
  - We rejected one entry per pair and region (more re-solves, more noise) and never reporting it (the user would not see what it costs).
- **D6. Not selected: `NotSelectedReason.STRONG_SUBSTITUTE`** (`strong_substitute`).
  - An option gets it when it would run together with a plan line's strong substitute, or is itself a BUNDLE of a strong pair.
  - The plan SKUs it would run with go in the existing `cannibalises` field. So `cannibalises` names the SKUs behind CANNIBALISES and STRONG_SUBSTITUTE alike.
  - The web app reads "Strong substitute of SKU0195, which the plan promotes at the same time".
  - We rejected a new `substitutes_of` field: every `run_optimizer` result would change shape, and every planner cassette would miss.
- **D7. `validate_plan` checks it: `ViolationCode.STRONG_SUBSTITUTES`.**
  - `PlanFacts.substitutes` carries the relations model's detected pairs among the plan's SKUs, with their θ. `optimizer.plan_facts` fills it from `OptionFacts.substitutes`, and validation applies the policy's threshold.
  - There is one violation per pair and region, for example "SKU0194 and SKU0195 are strong substitutes (estimated θ 0.54, at least 0.35) promoted together in North: promote one of them, or run them in different weeks or segments".
  - The constraint checklist puts it on the Policy row (ADR 0067).
  - So every plan the solver accepts still passes `validate_plan` (ADR 0012), and the eval's constraint check covers the rule too.
- **D8. Never relaxed.**
  - The rule is company policy. It is in the closest-plan model, the main solve and both relaxation re-solves (ADR 0044).
  - When it alone makes a clearance target unreachable, the relaxation lowers the target and `policy_binds` is true.
  - It is not among an infeasible request's binding constraints, which stay the missed targets and the relaxed constraints.
  - `relaxation_amendment` refuses it as it refuses the margin floor.
- **D9. Every pairwise `y_ij` stays**, guarded pairs included. The binding re-solve without the rule needs them, and there is one model builder.
- **D10. Where the code lives.**
  - The groups are built with the problem (`_guard_groups`) and added in `_Problem._variables(model, guard=...)`.
  - `solve(drop=_GUARD)` turns them off. Top-level `solve()` is untouched: #156 owns post-solve validation there.
- **D11. Tests.**
  - Unit tests on hand-built options (`test_solve_substitutes.py`):
    - the guard holds;
    - one of the pair is dropped, or shifted to other weeks or another segment;
    - different regions, and a θ below the threshold, run together;
    - a BUNDLE partner counts;
    - the binding entry appears only when dropping the rule gains;
    - a swap that breaks the rule does not make the budget bind;
    - the not-selected reason;
    - the closest plan to a clearance target keeps the rule.
  - The existing hypothesis properties now draw random detected substitutes (θ 0.2, 0.35 or 0.6 per SKU pair) into every small world. The brute force checks every candidate plan with `validate_plan`, which now includes the rule, so "optimal up to rounding" and "satisfies every hard constraint" cover the guard.
  - There are also `validate_plan`, `plan_facts`, Explainer and web-app tests.

## Solve time and determinism

The groups follow deterministically from the relations model and the options, sorted, with no randomness (ADR 0055 holds).

On the seed-42 world at week 104 (CP-SAT deterministic time, one worker, seed 0; the machine was heavily loaded, so wall seconds are not comparable):

| Brief | Main solve before | Main solve after | With the binding analysis, before | With the binding analysis, after |
|---|---|---|---|---|
| Speed-test brief (₹2 lakh, `tests/conftest.py`'s `DEMO_BRIEF`) | 3.02, OPTIMAL | 0.17, OPTIMAL | 6.73 in all: 3 of 6 constraints proven, 3 unproven | 3.25 in all: every constraint settled |
| ₹8 lakh with the 400g namkeen at 60% | 3.11, OPTIMAL | 0.08, OPTIMAL | 6.47 (a first run before; the second hit the wall-clock net under load) | 1.00 in all: every constraint settled |

- The groups prune the search: the main solve now needs about a twentieth of the work, far inside the 10 s budget.
- The binding analysis settles more in less work, because each re-solve is smaller.
- The one extra constraint to settle costs about 0.3 deterministic seconds on the speed-test brief. It binds there (a lower bound of ₹149), and on the ₹8 lakh brief (₹1,067).
- The speed-test brief's objective falls by 0.8%, from ₹1,72,384 to ₹1,71,007. That is what keeping SKU0032 and SKU0035 apart in North and West costs on the model's own numbers.

## Recording

A plan that changes changes the `run_optimizer` result the planner and the Explainer quote, so those requests miss their cassettes from the first changed attempt on. Before the change:

- the recorded `demo` session's revisions 1–3 promoted SKU0035 with SKU0032 and SKU0033 in North and West;
- 16 of the eval suite's 31 explained final plans promoted a guarded pair together.

The owner's plan:

- this PR re-records only what CI needs: the app sessions (`make record-cassettes`) and the three eval smoke scenarios that keep their own cassettes;
- the full 32-scenario eval re-record happens once, after #156 and #158 both merge.

## Consequences

- **New public names:**
  - domain: `ConstraintKind.STRONG_SUBSTITUTES`, `NotSelectedReason.STRONG_SUBSTITUTE`, `ViolationCode.STRONG_SUBSTITUTES` and `CompanyPolicy.strong_substitute_min_theta`;
  - guardrails: `SubstituteFacts`, `PlanFacts.substitutes` and `run_together`;
  - optimizer: `OptionFacts.substitutes`.
- The API types gain the three enum values. No migration is needed: reasons, binding constraints and open issues are stored as JSONB.
- **ADR 0033:** the pairwise term still charges every substitute pair. A strong pair can no longer run together, so its term is charged only in the binding re-solve without the rule.
- **ADR 0038:** the binding constraints can include `strong_substitutes`. The not-selected reasons include `strong_substitute`, and `cannibalises` names the SKUs behind either.
- **ADR 0051:** the Critic's heavy-cannibalisation risk still flags weaker pairs that lose too much together.
- **ADR 0065:** the eval property stays on the true θ at 0.5; planning never reads it.
- The rule can make a clearance target on one SKU of a strong pair harder to reach alongside the other. That shows as a lowered target with `policy_binds`.
