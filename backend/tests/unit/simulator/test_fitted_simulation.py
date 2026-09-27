"""`simulate` on a fitted demand model: its ranges agree with `predict` (ADR 0024, ADR 0042)."""

import pandas as pd
import pytest

from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, PromoPlan, Region, TargetSegment
from promopilot.models.demand import DemandModel, PredictionContext
from promopilot.models.relations import Relations
from promopilot.simulator import SimulationInputs, simulate
from tests.conftest import SMALL_AS_OF

Z90 = 1.2816


@pytest.fixture(scope="module")
def stock(small_dataset: GeneratedDataset) -> pd.DataFrame:
    inventory = small_dataset.inventory
    snapshot = inventory[inventory["snapshot_week"] == SMALL_AS_OF - 1]
    pooled = pooled_stock(snapshot, small_dataset.stores, CompanyPolicy())
    # Ample stock, so the ranges are the demand model's alone.
    return pooled.assign(available_stock=1e9)


def test_simulated_units_centre_on_predict_with_its_spread(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    stock: pd.DataFrame,
) -> None:
    model = small_models[0]
    skus = sorted(small_dataset.products["sku_id"])[:4]
    lines = tuple(
        PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=20,
            duration_weeks=2,
            start_week=SMALL_AS_OF + 2,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        )
        for sku_id, region in zip(skus, [Region.NORTH, Region.SOUTH] * 2, strict=True)
    )
    policy = CompanyPolicy()
    predicted = model.predict(lines, PredictionContext(policy=policy)).options

    result = simulate(
        PromoPlan(lines=lines),
        SimulationInputs(demand=model, stock=stock, policy=policy),
        n_runs=4_000,
        seed=1,
    )

    for simulated, (_, row) in zip(result.lines, predicted.iterrows(), strict=True):
        assert simulated.units.p50 == pytest.approx(row["units"], rel=0.06)
        spread = (simulated.units.p90 - simulated.units.p10) / (2 * Z90)
        assert spread == pytest.approx(row["units_std"], rel=0.25)
        assert simulated.revenue.p50 == pytest.approx(row["revenue"], rel=0.06)
        assert simulated.stockout_probability == 0.0
