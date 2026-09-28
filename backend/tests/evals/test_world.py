"""The eval's own world: a generated dataset, its oracle, and models fitted per as-of week
(ADR 0056)."""

from promopilot.datagen import GeneratedDataset
from promopilot.evals import EvalWorld
from promopilot.models.registry import ModelKind


async def test_models_are_fitted_on_the_history_before_the_week_once_and_kept(
    small_dataset: GeneratedDataset,
) -> None:
    world = EvalWorld(small_dataset, fit_seed=3)

    first = await world.models(40)
    again = await world.models(40)

    demand_entry, demand_model = await first.demand.get()
    relations_entry, relations_model = await first.relations.get()
    assert demand_model.as_of_week == 40
    assert (demand_entry.kind, demand_entry.as_of_week) == (ModelKind.DEMAND, 40)
    assert (relations_entry.kind, relations_entry.as_of_week) == (ModelKind.RELATIONS, 40)
    assert (await again.demand.get())[1] is demand_model
    assert (await again.relations.get())[1] is relations_model
    assert (await again.demand.get())[0] == demand_entry, "the same entry every time"


async def test_the_worlds_data_reads_at_the_scenarios_week(
    small_dataset: GeneratedDataset,
) -> None:
    world = EvalWorld(small_dataset)

    assert await world.data(30).default_as_of_week() == 30
    assert world.seed == small_dataset.seed


async def test_the_default_week_is_the_first_after_the_history_and_its_fit_is_kept(
    small_dataset: GeneratedDataset,
) -> None:
    world = EvalWorld(small_dataset, fit_seed=3)

    fitted = await world.fitted(world.default_as_of_week)

    assert world.default_as_of_week == small_dataset.ground_truth.history_weeks
    assert fitted.demand.as_of_week == world.default_as_of_week
    assert (await world.fitted(world.default_as_of_week)) is fitted
    sources = await world.models(world.default_as_of_week)
    assert (await sources.demand.get())[1] is fitted.demand
