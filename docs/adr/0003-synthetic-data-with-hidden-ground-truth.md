# Synthetic data with hidden ground truth

The organisers provide no data, so we generate a seeded synthetic retail dataset from a known true demand function (SPEC.md §8.3) and keep the true parameters in `data/ground_truth/`. We chose this over public retail datasets because reliability must be *measured*, not asserted: with known elasticities, substitute/complement pairs and an oracle demand function we can score elasticity recovery, relation detection, constraint satisfaction and plan regret, which no real dataset allows.

## Consequences

- Only `promopilot.datagen` (writes it) and `promopilot.evals` (oracle and metrics) may import from or read `data/ground_truth/`; an import-boundary test enforces this. Agents and learned models must never see it, or the evals would be self-fulfilling.
- Generated data and ground truth are gitignored and reproduced by `make data`; same seed means byte-identical output.
- Generator noise must be realistic: if models fail to recover the truth we report it honestly and downgrade the F3 × D2 claim rather than tune the generator to flatter the models.
