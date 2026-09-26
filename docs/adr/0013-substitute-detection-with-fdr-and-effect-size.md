# Substitute detection uses FDR control plus an effect-size threshold

SPEC §9.2 keeps a within-subcategory pair as a **substitute** when its cross-price effect θ is positive and significant at p < 0.05. With hundreds of pairs tested and roughly 85% of them not true substitutes, an uncorrected 5% false-positive rate alone pushes precision to about 0.74, under the §12.2 target of 0.8.

We keep a pair as a substitute only when both hold:

- its Benjamini–Hochberg-adjusted q-value, across all pairs tested in the fit, is below 0.05; and
- its estimated θ is at least a minimum effect size (config, default 0.1), so statistically real but commercially negligible effects do not enter the cannibalisation matrix.

We rejected a Bonferroni correction, which would cost too much recall at this number of tests, and BH alone, which still admits tiny effects that the optimiser would then penalise for no gain.

## Consequences

- The threshold is a config value recorded with the relations model version in the model registry.
- Complement detection (basket lift > 1.5 with minimum support) is unchanged; θ < 0 confirmation uses the same q-value rule where it is estimable.
