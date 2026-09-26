"""The API serves relations only while they were fitted on the live demand model (ADR 0033)."""

from datetime import UTC, datetime
from uuid import uuid4

from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.models.serving import LiveRelations


class Slot[T]:
    """Stands in for `LatestModel`: the loaded model, or None."""

    def __init__(self, loaded: tuple[RegisteredModel, T] | None) -> None:
        self.loaded = loaded

    async def get(self) -> tuple[RegisteredModel, T] | None:
        return self.loaded

    def set(self, loaded: tuple[RegisteredModel, T]) -> None:
        self.loaded = loaded


def entry(kind: ModelKind, version: int, **metrics: float) -> RegisteredModel:
    return RegisteredModel(
        model_id=uuid4(),
        kind=kind,
        version=version,
        trained_at=datetime(2026, 9, 26, tzinfo=UTC),
        as_of_week=104,
        metrics=metrics,
        artifact_path=f"{kind}-v{version}.pkl",
    )


DEMAND_V3 = (entry(ModelKind.DEMAND, 3), object())


async def test_relations_fitted_on_the_live_demand_model_are_served() -> None:
    loaded = (entry(ModelKind.RELATIONS, 5, demand_version=3.0), object())

    assert await LiveRelations(Slot(loaded), Slot(DEMAND_V3)).get() == loaded


async def test_relations_fitted_on_another_demand_version_are_not_served() -> None:
    stale = (entry(ModelKind.RELATIONS, 4, demand_version=2.0), object())

    assert await LiveRelations(Slot(stale), Slot(DEMAND_V3)).get() is None


async def test_nothing_is_served_without_both_models() -> None:
    loaded = (entry(ModelKind.RELATIONS, 5, demand_version=3.0), object())

    assert await LiveRelations(Slot(None), Slot(DEMAND_V3)).get() is None
    assert await LiveRelations(Slot(loaded), Slot(None)).get() is None


async def test_set_puts_a_just_trained_relations_model_live() -> None:
    relations = Slot[object](None)
    live = LiveRelations(relations, Slot(DEMAND_V3))
    trained = (entry(ModelKind.RELATIONS, 6, demand_version=3.0), object())

    live.set(trained)

    assert await live.get() == trained
