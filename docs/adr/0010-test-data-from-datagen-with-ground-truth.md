# Test data is generated on the fly, and tests may compare against its ground truth

Tests get their data by calling the synthetic generator with a small config and a fixed seed inside a pytest session fixture, rather than from committed Parquet fixtures (SPEC §13.3 described a committed 5-SKU, 2-region, 20-week dataset). Model-quality tests (marked `model`) use a somewhat larger config so elasticity, substitute and complement recovery can be measured. Generated fixtures cannot drift from the generator, and nothing large is committed.

Those tests may compare fitted parameters with the ground truth that `datagen` returns **in memory** for that fixture. This is a deliberate reading of the rule "only `promopilot.evals` and `promopilot.datagen` may touch `data/ground_truth/`": the rule protects production code (models, optimiser, agents) from learning or planning with true parameters, and a test checking a model against known truth is exactly how the reliability claim is earned before E9.

## Consequences

- Tests never read files under `data/ground_truth/`; they use the object `datagen` returns for their own fixture.
- The import-boundary test (SPEC §13.4) applies to `promopilot.*` packages: only `promopilot.evals` and `promopilot.datagen` may import the ground-truth types or read that directory. Test code under `backend/tests/` is exempt.
- Datagen must be fast at small configs (seconds), since many test sessions call it.
