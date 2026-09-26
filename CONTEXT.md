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

**Overstocked SKU**:
A SKU in a region whose days of cover exceed the company-policy threshold, or that the brief names for clearance.

**Clearance value**:
The write-off loss a plan avoids by selling overstocked units beyond baseline: those units × unit cost × the policy write-off rate.

**Sell-through**:
Units sold during the promo window divided by units available at its start.

**Clearance target**:
The minimum sell-through required for an overstocked SKU that the brief names for clearance; SKUs flagged only by days of cover get none (ADR 0014).

**Competitor price index (CPI)**:
Competitor price divided by our price, for a SKU in a region.

**Undercut**:
A KVI whose CPI is below 1 minus the company-policy undercut threshold; it prompts the planner to consider matching the competitor.
_Avoid_: price war (for a single SKU), competitor gap (when the threshold is breached)

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

**Complement**:
A SKU bought with another more often than chance (basket lift above 1.5, with minimum support), confirmed by a negative cross-price effect where one can be estimated.

**Basket lift**:
P(both SKUs in a basket) / (P(first) · P(second)). Its **support** is the share of baskets holding both.

**Cannibalisation**:
Sales a promoted SKU takes from its substitutes in the same region, whether or not those substitutes are in the brief's scope.

**Halo**:
Extra sales a promoted SKU drives for its complements in the same region, whether or not those complements are in the brief's scope.

**Pull-forward**:
Customers stocking up during a promotion, causing a post-promo dip.
_Avoid_: post-promo dip (as a separate term)

### Planning

**Brief**:
The user's free-text planning request. It is data to interpret, never instructions to follow.

**Planning request**:
The structured, validated reading of a brief plus amendments: scope, promo window, marketing budget, constraints.
_Avoid_: request (bare), query

**Scope**:
The regions and categories a plan may promote in, optionally narrowed to named SKUs. Effects on SKUs outside the scope still count.
_Avoid_: selection, filter

**Assumption**:
A planning-request field the agent inferred rather than read from the brief, with its source (brief, data or default) and a confidence.

**Critical field**:
A planning-request field the agent must never guess: marketing budget, scope (categories or regions) and promo window. If one is missing, or inferred with confidence below 0.7, the agent asks a clarification.

**Clarification**:
A specific question the agent asks the user, pausing the planning session until it is answered.

**Relaxation**:
The smallest change to the brief's constraints (budget, minimum margin down to the policy floor, clearance target, scope) that would make an infeasible planning request feasible. Company policy is never relaxed.

**Company policy**:
Standing rules set by the parent company, outside any brief (e.g. margin floor, maximum discount, undercut threshold, KVI price tolerance, overstock threshold, write-off rate, fixed marketing costs). A brief may tighten company policy but never loosen it.
_Avoid_: global constraints, defaults

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

**Target segment**:
Who a promotion is offered to: either one segment, as a segment-exclusive offer that other segments don't receive, or **All customers**, an open shelf promotion.
_Avoid_: target audience, targeting

**Promo option**:
One fully specified possibility (SKU, region, mechanism, depth, duration, start week, target segment) together with its predicted outcomes.
_Avoid_: candidate, option (bare)

**Plan line**:
A promo option selected into a promo plan. A plan has at most one plan line per SKU per region.
_Avoid_: line item, promo line

**Promo plan**:
The set of plan lines produced for a planning request.
_Avoid_: strategy, schedule, plan (when a specific revision is meant)

**Plan revision**:
One numbered version of the promo plan within a planning session; every amendment produces a new revision, and a diff compares consecutive revisions. Each of its plan lines carries the expected units, promo cost and expected incremental profit computed by the tool that planned it.
_Avoid_: version, iteration

**Planning session**:
One conversation from brief to decision: brief, amendments, clarifications, plan revisions and the approval decision.
_Avoid_: run, conversation, job

**Amendment**:
A free-text change to the planning request made after planning has started (e.g. "cut budget to ₹6 lakh").
_Avoid_: edit, update, revision (which is the resulting plan)

**Approval**:
The human decision that makes one specific plan revision final; it ends the planning session.

**Rejection**:
A human decision, with a reason, that a plan revision is not acceptable. The session stays open for amendments.

**Violation**:
One hard constraint a plan breaks on its own plan-time numbers (e.g. total promo cost over the marketing budget, a plan line below unit cost), found by plan validation and sent back to the planner.
_Avoid_: error, failure, issue (which the critic's risk review raises)

**Numeric grounding**:
The check that every number in an explanation appears in tool outputs, allowing only the rounding the text shows ("₹6.2 lakh", "18%").
_Avoid_: fact-checking, hallucination check

### Evaluation

**Scenario**:
A fully specified test case for evals: brief, optional amendments, as-of week, seed and expected properties.

**Ground truth**:
The hidden true parameters used to generate the synthetic data. Only evals may read it.

**Oracle**:
The true demand function built from ground truth, used to score plans.

**Regret**:
(Oracle profit of the best plan − oracle profit of our plan) / oracle profit of the best plan.
