# Synthetic world details: real calendar dates, overstock per SKU, hidden future competitor prices

SPEC §8 and ADRs 0003/0008 define the generated world; these details were left open and were confirmed with the owner in E2.

- **Real dates.** Week 0 starts Monday 2024-09-30, so 104 history weeks end on 2026-09-27 and the default as-of week (104) starts 2026-09-28, the real "today" of the build. Diwali 2026 (8 Nov, week 109) falls in the horizon, so the demo brief ("Plan Diwali promotions…") plans a real upcoming festival. Festival dates for 2024–2027 are approximate main-day dates in `datagen/config.yaml`. A festival's week gets its full intensity and the week before gets a lead-in share (pre-festival shopping). We rejected a calendar-year start and abstract week numbers, which would put the demo festival far away or make dates meaningless.
- **Overstock is per SKU, across all regions.** The 10–15% overstocked SKUs are overstocked in every region's stores (the amount varies by store), so a brief naming an overstocked SKU works in any region. We rejected a separate overstock set per SKU × region, which is more realistic but would often leave a brief's SKU overstocked in only one of its regions.
- **Future competitor prices live only in the ground truth.** The `competitor_prices` table holds history only; the horizon's prices exist only in `ground_truth.json`, for the oracle. Leakage of future competitor prices is then impossible by construction, rather than guarded by an as-of filter.
- **Pull-forward.** `promo_last_k_weeks` in SPEC §8.3 is the share of the previous k = 4 weeks in which that SKU was promoted to that segment (0 to 1), so longer promotions cause deeper dips. We rejected a plain indicator, which ignores duration.
- **Bundle partners in history.** A historical BUNDLE cuts both SKUs' prices by its depth for the targeted segments; the mechanism effect μ applies to the anchor only.

## Consequences

- SPEC §8.3 puts our own price in two terms: own-price elasticity β·log(p/p_ref) and competitor sensitivity γ·log(cp/p). A regression on our price alone recovers β − γ, so any elasticity estimator (the §8.4 sanity check and the E4 model) must control for the competitor price index to recover β.
- Seeds: each concern (catalogue, stores, competitors, demand, promotions, sales, …) draws from its own stream derived from the seed and the concern's name, so adding a concern never reshuffles the others.
