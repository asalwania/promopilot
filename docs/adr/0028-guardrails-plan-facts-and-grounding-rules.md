# Guardrails validate plan facts and ground numbers at the precision the text shows

E8 (#43) adds `promopilot.guardrails`, with `validate_plan(plan, request, policy)` for the Critic and `check_numeric_grounding(text, tool_outputs)` for the Explainer (SPEC §9.6). SPEC fixes what they check, not how. We chose these with the owner:

- **`validate_plan` takes its own input type, `PlanFacts`.** Each `LineFacts` is a plan line plus the plan-time numbers the planning tools computed for it: category, base price, unit cost and overstocked flag of the anchor SKU and of a BUNDLE's partner, and the line's expected units, P90 units, available stock, expected revenue, expected gross profit and promo cost. The domain's `PlanRevisionLine` lacks most of these, and `PromoPlan` refuses to build with two lines for one SKU in one region, so that check could never fire. `PlanFacts` accepts duplicates, so validation reports them. We rejected adding these fields to the domain types, which would touch the API read model, the frontend types and the E3 planner. We also rejected a fourth `facts` argument, which would change the ticket's signature.
- **Violations are frozen `Violation` values.** Each has a `ViolationCode` (`BUDGET`, `MIN_MARGIN`, `MARGIN_FLOOR`, `STOCK`, `MAX_DISCOUNT`, `BELOW_COST`, `WINDOW`, `MAX_SKUS`, `DUPLICATE_LINE`), a readable message, the SKU and region when the violation belongs to one, and the actual value and the limit. The planner gets enough to fix the plan, not just a label.
- **Margin has two codes, both plan-level (ADR 0007).** `MIN_MARGIN` fires when the blended expected margin is below the planning request's minimum margin. `MARGIN_FLOOR` fires when it is below the company-policy margin floor, even if the request sets no minimum. A plan below both gets both.
- **What each check compares.**
  - Budget: total promo cost against the marketing budget, with a 1-paisa allowance for float error (ADR 0015).
  - Stock: P90 units of the anchor against available stock (ADR 0004).
  - Max discount: the *effective* discount, so a charm price deeper than its depth and BOGO's 50% both count (ADR 0015).
  - Below cost: the anchor and a BUNDLE's partner, each at its effective price, unless that SKU is overstocked.
  - Window: the line's first and last weeks must lie inside the promo window.
  - Max SKUs: distinct promoted SKUs per category per region, a BUNDLE partner counting in its own category.
- **Grounding matches at the precision the text shows.** A number in the text is grounded when some tool-output number, rounded to the text's last shown digit, equals it. "₹6.2 lakh" covers ₹6,15,000–₹6,25,000. "₹6.20 lakh" covers only ±₹500. "18%" covers 17.5–18.5. A whole number is exact to its last digit, so "₹6,18,000" needs a tool value within 50 paise of it; write "₹6.2 lakh" to round. We rejected a fixed 1% relative tolerance. It would reject "₹6 lakh" for ₹6.4 lakh, a fair rounding, yet accept a precise-looking "₹6,18,000" for ₹6,22,000.
- **Parsing.** ₹, "Rs" and "INR" are optional prefixes. Lakh (lac) is 10⁵ and crore (cr) 10⁷. Indian (6,18,433) and Western (618,433) comma grouping are both read. "18%" or "18 percent" matches 18 or 0.18. Signs are ignored, so "a loss of ₹12,000" matches −12,000.
- **Exempt numbers.** The check skips:
  - numbers inside identifiers or words (SKU-0042, W12, 400g);
  - dates (2026-10-12, 12 Oct, Oct 12 2026, 12/10/2026);
  - bare 4-digit years from 1900 to 2100;
  - bare integers from 0 to 10, such as counts and ordinals.

  A number with ₹, a unit, a decimal point or a comma is never exempt. Week ids are not exempt; they are grounded against the tool outputs that name them.
- **Tool outputs are any JSON-like value or pydantic model.** Every numeric leaf counts, booleans excepted. Numbers written inside strings count too, both as written and with their lakh/crore multiplier. `check_numeric_grounding` returns a `GroundingReport` listing the ungrounded mentions as written.

## Consequences

- The tools that build a plan revision (E6 optimiser, E8 planner) must also produce its `PlanFacts`; the Critic never looks numbers up itself.
- An Explainer that rounds a whole number ("₹6,18,000") fails grounding and is regenerated or replaced by the template (#49). The explainer prompt should say to round with lakh/crore or decimals.
- Clearance targets and regional caps are not checked yet: the planning request does not carry them until E6 (#36), which adds their violation codes here.
