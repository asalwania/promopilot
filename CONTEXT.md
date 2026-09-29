# PromoPilot

An agentic planner that turns a retail promotions manager's plain-English brief into a promotion plan for a multi-region Indian retailer, subject to the parent company's policy and the brief's constraints, and approved by a human.

## Language

### Products and places

**SKU**:
A sellable product variant, e.g. "Crunchy Namkeen 400g".
_Avoid_: product, item, article

**Category / Subcategory**:
The two-level product hierarchy (e.g. Snacks → Namkeen). Substitution is assumed only within a subcategory.

**KVI**:
Key value item: a price-sensitive SKU whose competitor price gaps matter most to shoppers.

**Region**:
One of four geographic markets (North, South, East, West); the unit at which promotions are planned and run.
_Avoid_: zone, market, geography

**Store**:
One of the five outlets in a region; the level at which stock, sales and segment mix are recorded.
_Avoid_: outlet, branch

**Segment**:
A behavioural customer group: Value Seekers, Families, Premium, Young Urban. Never defined by protected attributes.
_Avoid_: audience, persona, cohort

### Time

**Week**:
The unit of time for history, planning and promotion duration.
_Avoid_: period

**As-of week**:
The week a planning session treats as "today": history before it is visible, everything from it onward is future. Defaults to the first week after the generated history.
_Avoid_: current date, now, planning date

**Promo window**:
The span of future weeks in which a plan's promotions must start and end, e.g. the weeks around Diwali.
_Avoid_: campaign period, horizon

### Prices, costs and stock

**Base price / Unit cost**:
A SKU's regular shelf price and what it costs us. Margin = (price − cost) / price.

**Available stock**:
For a SKU in a region, the sum over the region's stores of on-hand stock minus safety stock.
_Avoid_: inventory (when the pooled regional quantity is meant)

**Days of cover**:
How many days a region's stock of a SKU lasts at current demand: the region's on-hand stock divided by its stores' combined daily demand (ADR 0032).

**Overstocked SKU**:
A SKU in a region whose days of cover exceed the company-policy threshold, or that the brief names for clearance.

**Clearance value**:
The write-off loss a plan avoids by selling overstocked units beyond baseline: those units × unit cost × the policy write-off rate.

**Sell-through**:
The expected units a SKU sells in a region over the promo window, promotions included, divided by its available stock at the as-of week (ADR 0040).

**Clearance target**:
The minimum sell-through required, in every region of the scope, for an overstocked SKU that the brief names for clearance; SKUs flagged only by days of cover get none (ADR 0014).

**Clearance shortfall**:
How far a plan falls short of a clearance target that no plan within the other constraints reaches. The optimiser then returns the plan closest to every target and reports each shortfall; it is never a silent miss (ADR 0040). The request is infeasible, and a relaxation says what would fix it (ADR 0044).

**Competitor price index (CPI)**:
The competitor's latest price before the as-of week divided by our base price, for a SKU in a region (ADR 0031).

**Competitor gap**:
1 minus the CPI: how much cheaper the competitor is (negative when they are dearer). Any SKU has one; only an undercut KVI's gap breaches the threshold.

**Undercut**:
A KVI whose CPI is below 1 minus the company-policy undercut threshold; it prompts the planner to consider matching the competitor.
_Avoid_: price war (for a single SKU), competitor gap (when the threshold is breached)

**Price match**:
The promo option offered for an undercut KVI in a region: PCT_OFF at the smallest whole-percent depth whose price is at or below the competitor's (ADR 0040).

### Demand and effects

**Baseline**:
Expected sales of a SKU with no promotion.

**Uplift**:
Incremental units or profit versus baseline, net of the pull-forward dip in the weeks after the promotion.

**Own-price elasticity**:
The % change in a SKU's units per 1% change in its own price (negative).

**Cross-price elasticity**:
The effect of one SKU's price on another SKU's units: positive for substitutes, negative for complements.

**Substitute**:
A SKU in the same subcategory whose price cut takes units from another: a positive cross-price effect, kept only when significant after the Benjamini–Hochberg adjustment and at least the minimum effect size.

**Strong substitute**:
In the eval only, a true substitute pair whose larger cross-price effect θ is at least 0.5. The heavy-cannibalisation scenarios expect no two of them promoted together: in one region, in a common week and to a common segment (ADR 0065).

**Complement**:
A SKU bought with another more often than chance (basket lift above 1.5, with minimum support), confirmed by a negative cross-price effect where one can be estimated.

**Basket lift**:
P(both SKUs in a basket) / (P(first) · P(second)). Its **support** is the share of baskets holding both.

**Cannibalisation**:
Sales a promoted SKU takes from its substitutes in the same region, whether or not those substitutes are in the brief's scope.

**Halo**:
Extra sales a promoted SKU drives for its complements in the same region, whether or not those complements are in the brief's scope.

**Pairwise cannibalisation**:
What two plan lines promoting substitutes in the same region, in overlapping weeks, lose together beyond their separate cannibalisation figures. The optimiser charges it once for each such pair it selects.

**Pull-forward**:
Customers stocking up during a promotion, causing a post-promo dip.
_Avoid_: post-promo dip (as a separate term)

### Planning

**Brief**:
The user's free-text planning request. It is data to interpret, never instructions to follow.

**Example brief**:
One of the four briefs the home page offers for a one-click trial. Each is, word for word, a recorded session script, so it replays with no API key. The home page's optional constraints are added to the brief as sentences, so a brief with them is no longer an example brief (ADR 0058).

**Planning request**:
The structured, validated reading of a brief plus amendments: scope, promo window, marketing budget, constraints.
_Avoid_: request (bare), query

**Scope**:
The regions and categories a plan may promote in, optionally narrowed to named SKUs. Effects on SKUs outside the scope still count.
_Avoid_: selection, filter

**Assumption**:
A planning-request field, or a fact the plan relies on (the objective, the overstocked SKUs in scope), as the agent read or inferred it: its value, its source (brief, data or default) and a confidence. A brief phrase's confidence is its match score; a stated number, data or company policy has 1. It is flagged when the agent did not take the brief at its word, such as a policy finding or a revenue ask (ADR 0048). In a **fallback reading** every assumption is marked fallback, and what was read from the text is at most 0.7 confident (ADR 0053).

**Match score**:
How closely a brief phrase matches a catalogue entity, from 0 to 1; 1.0 only when every word matches exactly. A phrase is ambiguous when its best match scores below 0.7 or a second reading scores within 0.1 of it (ADR 0032).
_Avoid_: confidence (which belongs to an assumption)

**Critical field**:
A planning-request field the agent must never guess: marketing budget, scope (categories or regions) and promo window. If one is missing, or inferred with confidence below 0.7, the agent asks a clarification.

**Clarification**:
A specific question the agent asks the user, pausing the planning session until it is answered, together with the user's answer in their own words. The agent asks about a critical field, and about a clearance with no figure or unclear SKUs; it then reads the brief again with every answer so far (ADR 0048), by rules in a **fallback reading** (ADR 0053).

**Infeasible**:
A planning request is infeasible when no plan reaches every clearance target within its other constraints; the empty plan keeps every other constraint, so nothing else can make it so. The optimiser says so only when it has proven it: a timeout is `FEASIBLE`, never `INFEASIBLE`. The closest plan still comes back, with its clearance shortfalls and a relaxation (ADR 0044).

**Relaxation**:
The smallest change to the brief's constraints that would make an infeasible planning request feasible: a higher marketing budget or regional budget cap, a lower minimum margin (down to the margin floor), a looser brief promoted-SKU cap (up to policy's), a brief-enabled KVI price tolerance turned off, or a lower or dropped clearance target. "Smallest" is the least sum of each change as a share of the brief's value. Company policy is never relaxed, and scope is not relaxed (ADR 0007, ADR 0044).

**Policy binds**:
Said of a relaxation when no change to the budget, caps, minimum margin or KVI tolerance alone would reach every clearance target, so a target must come down; the relaxation then gives the most sell-through company policy allows (ADR 0044).

**Binding constraint**:
A plan-level constraint (marketing budget, regional budget cap, minimum margin or margin floor, promoted-SKU cap per category and region, clearance target, KVI price tolerance) whose removal would give the optimiser a strictly better objective. It is unproven when the solver ran out of time before settling it (ADR 0038, ADR 0040). For an infeasible request, the binding constraints are the clearance targets the plan misses and the constraints the relaxation changes (ADR 0044).
_Avoid_: active constraint, bottleneck

**Company policy**:
Standing rules set by the parent company, outside any brief (e.g. margin floor, maximum discount, undercut threshold, KVI price tolerance, overstock threshold, write-off rate, fixed marketing costs). A brief may tighten company policy but never loosen it.
_Avoid_: global constraints, defaults

**Policy finding**:
A brief value that would loosen company policy (a minimum margin below the margin floor, a looser promoted-SKU cap or KVI price tolerance). Planning keeps the policy value and reports the finding (ADR 0007, ADR 0040).

**Margin floor**:
The company-policy lowest value any planning request's minimum margin may take.

**Objective**:
What a plan maximises: incremental gross profit, net of cannibalisation and including halo. There is only one objective.
_Avoid_: goal, KPI

**Promo cost**:
What a plan line spends from the marketing budget: discount funding (base price minus effective price, times the expected units sold to the target segment) plus the mechanism's fixed marketing cost.
_Avoid_: spend, trade spend, promo investment

**Marketing budget**:
The cap on a plan's total expected promo cost, set by the brief.
_Avoid_: budget (when a regional cap is meant)

**Regional budget cap**:
An optional cap the brief sets on the promo cost spent in one region, on top of the marketing budget.

**Minimum margin**:
The lowest blended expected margin the plan lines together may have. Separately, no plan line may sell below unit cost unless its SKU is overstocked.
_Avoid_: margin floor (reserved for the company-policy minimum)

**Mechanism**:
How a promotion gives value to the shopper. Every mechanism reduces to an effective unit price plus its own demand effect. One of:
- **PCT_OFF**: a percentage off the base price.
- **BOGO**: buy one, get one free (an effective 50% off per unit when bought in pairs). No other buy-X-get-Y variants.
- **FIXED_PRICE**: a charm price point (ending in 9, e.g. ₹99) at or just below a discount level.
- **BUNDLE**: a SKU sold together with a complement at a percentage off the pair's price.
_Avoid_: promo type, offer type

**Mechanism comparison**:
For a SKU in a region, each mechanism's best promo option by value, on the demand model's expected numbers. A plan line's own mechanism is shown as the plan line itself. A mechanism whose every option breaks a per-line rule is listed with the rules it breaks. BUNDLE appears only when the SKU has a detected complement (ADR 0041).
_Avoid_: mechanism drawer (the UI that shows it), mechanism table

**Target segment**:
Who a promotion is offered to: either one segment, as a segment-exclusive offer that other segments don't receive, or **All customers**, an open shelf promotion.
_Avoid_: target audience, targeting

**Promo option**:
One fully specified possibility (SKU, region, mechanism, depth, duration, start week, target segment) together with its predicted outcomes. A planning request's promo options are enumerated in full and pruned when they are deeper than the maximum discount, below unit cost without overstock, a repeated charm price, or when their P90 units exceed available stock (ADR 0035). The set that survives is a **candidate set**, which the optimiser selects plan lines from.
_Avoid_: candidate, option (bare)

**P90 units**:
The units a promo option sells at the 90th percentile of its prediction: mean + 1.2816 × std. They must fit within available stock.

**Plan line**:
A promo option selected into a promo plan. A plan has at most one plan line per SKU per region.
_Avoid_: line item, promo line

**Promo plan**:
The set of plan lines produced for a planning request.
_Avoid_: strategy, schedule, plan (when a specific revision is meant)

**Plan revision**:
One numbered version of the promo plan within a planning session; every amendment produces a new revision, and a **revision diff** compares consecutive revisions. Each of its plan lines carries the expected units, promo cost and expected incremental profit computed by the tool that planned it.
_Avoid_: version, iteration

**Revision diff**:
What changed from the previous plan revision, stored on the new one: plan lines added, removed and changed (matched by SKU and region; changed when the decision differs, not just its expected numbers), the objective and promo-cost deltas, and the planning-request changes that caused them. It is computed deterministically; the explainer says it in words (ADR 0052).
_Avoid_: delta (for the whole diff), changelog

**Simulation**:
The Monte Carlo runs of a promo plan: each run samples the demand model's terms within their uncertainty and weekly demand noise, and caps units at available stock. It reports P10/P50/P90 of each plan line's and the plan's outcomes (ADR 0042).
_Avoid_: forecast, scenario (which belongs to evals)

**Competitor reaction**:
A simulation's optional price-war stress test: in each run, the competitor matches each plan line's discount with a given match probability, drawn per line. A matched competitor cuts its price by the same share, so the competitor price index returns to where it was before the promotion, and undercut-sensitive SKUs (positive competitor sensitivity γ) lose the demand the discount won from the competitor (ADR 0045). A re-simulation with one replaces the stored simulation, which is then labelled a stress test until a plain re-simulation (ADR 0068).
_Avoid_: price war (for the simulation setting), scenario (which belongs to evals)

**Stock-out probability**:
The share of a simulation's runs in which a plan line's demand reached the available stock of its SKU (or of a BUNDLE's partner); for a region, the share in which at least one of its plan lines did.
_Avoid_: stock-out risk (as a number)

**Planning session**:
One conversation from brief to decision: brief, amendments, clarifications, plan revisions and the approval decision.
_Avoid_: run, conversation, job

**Amendment**:
A free-text change to the planning request made while a plan revision waits for a decision, or after it is rejected (e.g. "cut budget to ₹6 lakh", "drop West"). The context agent reads the brief again with every amendment, oldest first, and a new plan revision is planned. Accepting a relaxation is an amendment that states each change exactly (ADR 0052).
_Avoid_: edit, update, revision (which is the resulting plan)

**Approval**:
The human decision that makes one specific plan revision final; it ends the planning session.

**Rejection**:
A human decision, with a reason, that a plan revision is not acceptable. The session stays open for amendments.

**Decision**:
An approval or a rejection of one named plan revision, with when it was made (and, for a rejection, why). Every decision of a planning session is kept in order as its audit trail; the session page shows its amendments in the same trail, in time order (ADR 0066).
_Avoid_: vote, sign-off

**Planner note**:
A sentence the planner adds to a plan revision's explanation from tool outputs: how the plan answers each undercut KVI ("Competitor is 5.1% cheaper on SKU0002 in North; matching on 1 SKU"), and, when the default sequence planned it, why (ADR 0049). The undercut sentences are also kept on the explanation as its competitor response, for the session page's competitor card (ADR 0068).
_Avoid_: planner explanation, rationale (which is per plan line)

**Default sequence**:
The deterministic planning path with no LLM: generate every promo option, optimise, simulate. The planner agent falls back to it when the LLM is unavailable or it reaches no optimiser plan, and the plan revision is then **degraded** (SF-03, ADR 0049).
_Avoid_: fallback planner, naive planner

**Fallback reading**:
The Context agent's reading of the brief, answers and amendments by strict deterministic rules when the LLM is unavailable or replay has no cassette: exact catalogue and holiday names, rupees and percentages only where the text states them, placed by their cue words. What it reads is a low-confidence assumption (0.7); what it cannot read is asked (SF-03, ADR 0053).
_Avoid_: fallback parser, rule-based context

**Open issue**:
A violation or a risk finding that a plan revision still has when it goes for approval. It is listed on the revision; it does not block approval, but an infeasible revision cannot be approved.
_Avoid_: error, warning

**Constraint checklist**:
A plan revision's pass or fail for each group of hard constraints (budget, minimum margin, stock, clearance, company policy), read from its open issues: a group fails when one of its violations is open. Clearance also fails on a clearance shortfall, and is not set when the brief names no target (ADR 0067).
_Avoid_: validation report

**Not-selected option**:
One of the up to five best promo options, one per SKU and region, that the optimiser left out of a plan, with why: low uplift, stock, policy, a budget, margin, cap, clearance or KVI rule it would break, cannibalisation, or the time limit (F-01 AC3, ADR 0038).
_Avoid_: rejected option, alternative

**Risk finding**:
A risk the critic's risk review flags in a plan that may break no hard constraint: over-concentration (one plan line, category or region takes too much of the promo spend), heavy cannibalisation (a line's substitutes lose too much of its incremental profit) or stock-out risk (a line runs out in too many simulated runs). It carries feedback for the planner. Found deterministically; the LLM only words the feedback (ADR 0051).
_Avoid_: warning, risk score

**Planner attempt**:
One plan the planner produces within a planning round. The critic reviews each attempt and sends its findings back at most 3 times, and stops early when an attempt's findings repeat the previous attempt's exactly; only the best attempt becomes a plan revision (ADR 0051, ADR 0059).
_Avoid_: iteration (which counts every planner run in a session), draft revision

**Checkpoint**:
The saved state of a planning session's agent graph after a step. A session paused at an interrupt (approval, clarification) resumes from its checkpoint, even after an API restart.
_Avoid_: snapshot, save point

**Trace event**:
One numbered step of a planning session's agent graph: a node starting or finishing, a tool call, a decision, a clarification, a finding, or the tokens one LLM call used and cost. A session's trace events are kept in order and stream live to the session page; its token usage is their sum.
_Avoid_: log line, message, activity

**Violation**:
One hard constraint a plan breaks on its own plan-time numbers (e.g. total promo cost over the marketing budget, a plan line below unit cost), found by plan validation and sent back to the planner.
_Avoid_: error, failure, issue (which the critic's risk review raises)

**Numeric grounding**:
The check that every number in an explanation appears in tool outputs, allowing only the rounding the text shows ("₹6.2 lakh", "18%").
_Avoid_: fact-checking, hallucination check

**Explanation**:
What the explainer writes for a plan revision: a summary of the plan and a rationale for each plan line, whose every number passes numeric grounding. Money is shown in lakh or crore from ₹1 lakh up (ADR 0050).
_Avoid_: description, commentary

**Rationale**:
The part of an explanation that says why one plan line is in the plan: its "why chosen" reasons, how its mechanism compares, and its risks.
_Avoid_: reason (which is one code of "why chosen"), justification

**Template explanation**:
The deterministic explanation written from the plan revision's own numbers. It is the fallback when the LLM's answer fails numeric grounding twice, misses a plan line twice, or the LLM is unavailable, and the explanation records why it was used.
_Avoid_: default explanation, canned text

### Evaluation

**Scenario**:
A fully specified test case for evals: brief, optional amendments, as-of week, seed and expected properties.
It also has its group, the answers the manager gives if asked, and the planning-request fields it states (labels). One YAML file each (ADR 0056).

**Expected property**:
Something a scenario's outcome must show, from a closed vocabulary, such as "asks about the marketing budget" or "excludes West after the amendment". It is never an exact plan.
_Avoid_: assertion, expectation

**Final plan revision**:
The plan revision a scenario's session waits for approval with once every answer and amendment is in. It is the one the eval scores.

**Constraint satisfaction**:
The share of final plan revisions that keep every hard constraint on their own plan-time numbers, checked by plan validation (ADR 0012). Target 100%.

**Oracle breach rate**:
The share of the same plans whose true outcome, by the oracle, breaks the budget, the minimum margin or the stock. Reported, with no target (ADR 0012).

**Extraction accuracy**:
The share of a scenario's labelled planning-request fields that the final planning request reads right, by field matching rules. Target 95% (ADR 0062).

**Clarification behaviour**:
The share of vague or conflicting scenarios' sessions that ask about, or flag, a field the scenario names. Target 100% (ADR 0062).

**Unneeded ask**:
A question a session of any other scenario asks that its scenario does not expect. Counted, with no target (ADR 0062).
_Avoid_: false clarification

**Infeasibility handling**:
The share of infeasible-constraint scenarios' sessions whose final plan revision is declared infeasible, names a binding constraint and proposes a relaxation. Target 100% (ADR 0062).

**Grounding pass rate**:
The share of the Explainer's runs, where the LLM answered, whose explanation passed numeric grounding. A run where the LLM was unavailable is not scored. Target 98% (ADR 0062).

**Model recovery**:
How close the fitted models, as of the eval world's default week, come to the ground truth. It covers the median absolute % error of the own-price elasticities, and the precision and recall of the substitutes and complements. The same rows report the baseline's holdout WAPE, which needs no ground truth (ADR 0064).
_Avoid_: model accuracy

**Ground truth**:
The hidden true parameters used to generate the synthetic data. Only evals may read it.

**Oracle**:
The true demand function built from ground truth, used to score plans.

**Rule-based baseline**:
The simple plan a final plan must beat: 20% off the top 10 sellers in scope, to All customers, over the promo window, dropped from the bottom until it fits the budget. The harness builds it from the final planning request (ADR 0063).
_Avoid_: baseline (which is sales with no promotion), naive plan

**Best plan**:
Our own optimiser run on true-parameter predictions for the final planning request: the plan regret is measured against. The harness builds it (ADR 0063).
_Avoid_: optimum, oracle plan

**Plan quality**:
The share of scenarios whose every scored final plan earns more, by the oracle, than the rule-based baseline. Target 90% (ADR 0063).

**Regret**:
(Oracle profit of the best plan − oracle profit of our plan) / oracle profit of the best plan, where oracle profit is the objective: incremental profit plus clearance value. It is signed; when the best plan earns nothing, matching it is 0 and earning less is 1. Target: median 10% or less (ADR 0063).

**Consistency**:
How alike a scenario's runs plan: the mean Jaccard overlap of the SKUs every two runs' final plan revisions promote. Target 0.9; it needs at least two runs per scenario (ADR 0063).
