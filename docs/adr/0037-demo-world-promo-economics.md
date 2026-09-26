# Promotions can pay in the synthetic world: stronger mechanism effects, a smaller pull-forward dip floored at 0 when fitted, ₹500 fixed cost per line-week

#109 found that on the seed-42 demo brief (Snacks and Beverages, North and West, Diwali weeks 108–109, ₹2 lakh, as of week 104) none of the 10,981 promo options had positive incremental profit. The only options with positive value were clearance lines on overstocked SKUs, so the optimiser selected 4 clearance lines (objective ≈ ₹11,248). We measured where the loss came from and chose the fix with the owner. This ADR amends the consequences of ADR 0015, the world details of ADR 0016 and the fitted pull-forward of ADR 0024.

## Root cause: the world's economics, not the model or the accounting

- **The model is not the cause.** Fitted terms match the truth:
  - β has a median absolute error of 6–12% per segment, with no bias;
  - γ, φ and μ for PCT_OFF have unbiased means.

  Per option, the model and the oracle agree:
  - correlation 0.994 on incremental profit before the fixed cost;
  - the median model/oracle lift ratio is 0.999.
- **The truth agrees there was nothing to promote.** Scored alone by the oracle, none of the 10,981 options had positive incremental profit. Every option with positive value was a clearance line.
- **Price cuts lost gross profit.** In scope, the effective own-price elasticity is β − γ, because our price is in the competitor term too (ADR 0016). It averaged −2.28. At 25–40% margins, a small cut adds gross profit only when |β − γ| exceeds 1 / margin, about 3.1. Only 15.5% of SKU × segment pairs did.
- **The mechanism effect was too small, and the dip too big.**
  - The mechanism effect (μ ≈ 0.10 for PCT_OFF) barely offset the price loss.
  - The pull-forward dip (φ ≈ 0.24 on average, ADR 0016) cost about φ × one baseline week of sales per promoted week, whatever the depth.
  - For non-clearance options, the median promo-week gain in gross profit was about ₹0, against a median pull-forward loss of ₹150–300.
- **The fixed cost only made it worse.** ₹2,000 per line-week is close to the median baseline gross profit per SKU-region-week (₹2,067). Even at zero fixed cost, though, the best non-clearance option was worth only ₹724 to the oracle. No fixed-cost change alone gave a plan with positive incremental profit.

## Decision

- **Stronger mechanism effects.** The ranges in `datagen/config.yaml` are three times wider: PCT_OFF 0.15–0.45, FIXED_PRICE 0.24–0.54, BOGO 0.45–0.90 and BUNDLE 0.30–0.60 log-units. This is the display, feature and "deal" response beyond the price itself that real promotions get.
- **A smaller pull-forward dip.** φ is drawn from 0.05–0.20 (was 0.1–0.4).
- **A lower fixed marketing cost.** The defaults are ₹500 for PCT_OFF and FIXED_PRICE, ₹750 for BOGO and ₹1,000 for BUNDLE, per line-week. It stays per line-week, in the same 1 : 1 : 1.5 : 2 ratios (ADR 0015).
- **The fitted pull-forward φ is floored at 0 after shrinkage** (amends ADR 0024).
  - With a smaller true φ, its standard error (about 0.05–0.07) now straddles zero for some SKUs. The fit gave φ < 0, a post-promotion lift, on 1 of 24 SKUs in the small test world, 2 of 32 in the medium one and 1 of 200 in seed 42.
  - SPEC §8.3 fixes the dip's sign, and a negative φ would over-value those options. So `coefficients()` reports max(φ, 0).
  - The standard error is kept as it is, so the E7 simulator may still sample a small negative φ.
  - We rejected leaving φ unconstrained, which would only weaken the test. We also rejected keeping a larger true φ, which was the other half of the fix.
- **Elasticities, margins and the promo history are unchanged.** SPEC §8.3's demand function is unchanged; only the drawn ranges move. Every other draw keeps its value, because each μ and φ is `uniform(a, b)` from the same seeded stream (ADR 0016).

We rejected:
- **Changing only the fixed cost** (per line, halved, ₹500, 2% of baseline revenue, or zero). Every variant leaves the demo plan with negative incremental profit, and at most 5–7 small non-clearance lines.
- **More elastic demand** (β shifted by −1). On its own, it still found no profitable non-clearance line at the current fixed cost.
- **Supplier-funded discounts.** They are realistic, but would change the ADR 0005 economics for the demand model, oracle, options and budget.
- **Accepting a clearance-only demo.**

## Result on the seed-42 demo brief

- `generate_options` keeps 10,396 of 28,980 options:
  - 1,935 have positive value, 519 of them without clearance;
  - 808 have positive incremental profit.
- The CP-SAT optimiser (#34, ADR 0036) selects 35 lines, 21 of them without clearance (OPTIMAL).
  - The mechanisms are 18 FIXED_PRICE and 17 PCT_OFF.
  - Objective: ₹172,384. Promo cost: ₹199,909. Model incremental profit: +₹86,124.
  - The oracle, scoring the plan jointly: incremental profit +₹66,607, clearance value ₹86,654, blended margin 26.0%.
  - This meets #109's acceptance criterion: objective > 0, oracle incremental profit > 0, and at least one line without clearance.
- **The optimiser is now slower.** With 1,935 eligible options instead of 92, the solve takes about 18 s. About 14 s of that is `pairwise_cannibalisations` for 3,796 pairs, and CP-SAT takes about 4 s. This is above SPEC's 10 s optimiser budget and is left for a follow-up on the pairwise batch.
- Model quality on the seed-42 world:
  - median elasticity recovery error 8.1% (was 7.6%);
  - fitted μ means match the truth (PCT_OFF 0.292 vs 0.293, BOGO 0.669 vs 0.671; BUNDLE is overstated, 0.51 vs 0.45, as before);
  - substitutes precision/recall 0.87/1.00, complements 1.00/0.97;
  - baseline WAPE 0.44 / 0.25 / 0.13.

## Known limitations, accepted

- **Non-clearance lines are shallow.** Almost every one is 5% off, for All customers, over 1–2 weeks. μ and φ apply once per promotion whatever its depth, while the price loss grows with depth, so the shallowest cut earns the most. Deeper cuts still pay where they clear overstock.
- **Clearance lines take most of the budget.** Their clearance value is large, and the optimiser rightly prefers them.
- **BOGO appears only on overstocked SKUs.** At 50% off, it sells below cost at every category margin, so it is pruned unless the SKU is overstocked (ADR 0007, ADR 0035).

## Consequences

- **Data and models must be regenerated.** `make data && make train` must be rerun: the generated data and ground truth change, and so does every model fitted on them.
- **The LLM cassette is unaffected.** Its request hash covers the prompt and the week table, and neither changes.
- **The demo outcome is guarded by the eval, not a unit test.** The #58 eval scenario for the demo brief asserts three things:
  - the plan objective is > 0;
  - the oracle's plan incremental profit is > 0;
  - the plan has at least one non-clearance line.

  A unit test only checks the world's economics (`tests/evals/test_oracle.py`): a one-week 5% PCT_OFF pays, net of pull-forward and the default fixed cost, on at least 10 of the demo scope's 100 SKU-regions without clearing stock. It measures 22.
- **Tests that hand-compute the oracle** pin their own ₹2,000 policy, so they no longer depend on the default.
- **#34's fitted-world `run_optimizer` test now runs on the default policy.** It had used a zero-fixed-cost policy with a 10% margin floor, because the defaults selected nothing.
- **Plan-quality evals change.** The rule-based baseline ("20% off top 10 sellers", SPEC §12.2) still loses money in this world, so "beats baseline" is easy. Regret against the optimiser on true parameters is now measured against a real mix of lines.
