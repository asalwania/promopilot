"""Which relations model the API serves: the latest, while it matches the live demand model.

A relations version records the demand version it was fitted on (ADR 0029). Its cross
effects are read against that demand model's baseline, so it is served only while that
demand version is live; otherwise tools and endpoints report no relations model (ADR 0033).
"""

from typing import Any, Protocol

from promopilot.models.registry import RegisteredModel


class _Loaded[T](Protocol):
    async def get(self) -> tuple[RegisteredModel, T] | None: ...


class _Swappable[T](_Loaded[T], Protocol):
    def set(self, loaded: tuple[RegisteredModel, T]) -> None: ...


class LiveRelations[T]:
    """The latest relations model (`LatestModel`), served only on the live demand model."""

    def __init__(self, relations: _Swappable[T], demand: _Loaded[Any]) -> None:
        self._relations = relations
        self._demand = demand

    async def get(self) -> tuple[RegisteredModel, T] | None:
        loaded = await self._relations.get()
        demand = await self._demand.get()
        if loaded is None or demand is None:
            return None
        if loaded[0].metrics.get("demand_version") != float(demand[0].version):
            return None
        return loaded

    def set(self, loaded: tuple[RegisteredModel, T]) -> None:
        """Make a relations model just registered the live one (a retrain)."""
        self._relations.set(loaded)
