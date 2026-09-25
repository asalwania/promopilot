# One profit objective, with explicit promo economics

The planner maximises a single **objective**: incremental gross profit over baseline, net of **cannibalisation** and **pull-forward** and including **halo** and **clearance value**. We rejected a selectable objective (profit / revenue / units) because the oracle, the regret metric and the "beats the rule-based baseline" target are all profit-based, and a second objective would double the eval surface for no demo gain. Briefs asking for revenue or volume get an Assumption saying we optimise profit.

The economics behind that number, fixed so the demand model, optimiser, simulator and oracle all agree:

- **Uplift is net of pull-forward**: the dip in the weeks after a promotion (up to 4, as estimated) is subtracted, so long or deep promotions are not over-valued.
- **Cannibalisation and halo count for every SKU in the region**, including SKUs outside the brief's scope (promoting chips in a Snacks-only brief still credits the cola halo and debits sister-chip losses).
- **Promo cost** = discount funding + fixed marketing cost. Discount funding is (base price − effective price) × expected units sold to the target segment; a BUNDLE's discount is split between its two SKUs pro-rata by base price. The **marketing budget** caps total *expected* promo cost; P90 spend is reported, not constrained.
- **Clearance value** = overstocked units sold beyond baseline × unit cost × the company-policy write-off rate.
- Every **mechanism** reduces to an effective unit price plus its own demand effect: PCT_OFF (d% off), BOGO (buy-1-get-1 only, 50% effective), FIXED_PRICE (charm price ending in 9 at or just below a discount level), BUNDLE (pair with a complement at 10–25% off the pair price).
- A plan line must start and end inside the **promo window**.
