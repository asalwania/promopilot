"""The model registry (SPEC §9.1, SF-02): trained model versions in Postgres, artifacts on disk.

Each registered model gets the next version for its kind. Its artifact is a pickle under the
artifact directory (MODEL_DIR), and the row stores the path relative to it, so the same row
resolves both natively (`../models`) and in Docker (`/app/models`) (ADR 0023). Artifacts are
only ever written by this module: never load a pickle from anywhere else.
"""

import os
import pickle
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import model_registry

log = structlog.get_logger(__name__)


class ModelKind(StrEnum):
    DEMAND = "demand"
    RELATIONS = "relations"


@dataclass(frozen=True)
class RegisteredModel:
    model_id: UUID
    kind: ModelKind
    version: int
    trained_at: datetime
    as_of_week: int
    metrics: dict[str, float]
    artifact_path: str


class ModelRegistry:
    def __init__(self, engine: AsyncEngine, artifact_dir: Path) -> None:
        self._engine = engine
        self._artifact_dir = artifact_dir

    async def register(
        self, kind: ModelKind, model: object, *, as_of_week: int, metrics: dict[str, float]
    ) -> RegisteredModel:
        """Record the next version of `kind` and save its artifact, or neither."""
        model_id = uuid4()
        async with self._engine.begin() as connection:
            latest = await connection.execute(
                select(func.max(model_registry.c.version)).where(model_registry.c.kind == kind)
            )
            version = (latest.scalar_one() or 0) + 1
            artifact_path = f"{kind}-v{version}.pkl"
            row = await connection.execute(
                insert(model_registry)
                .values(
                    model_id=model_id,
                    kind=kind.value,
                    version=version,
                    as_of_week=as_of_week,
                    metrics=metrics,
                    artifact_path=artifact_path,
                )
                .returning(*model_registry.c)
            )
            # Inside the transaction: a failed write rolls the row back.
            self._save(model, artifact_path)
            return _entry(row.one()._mapping)

    async def list(self, kind: ModelKind | None = None) -> list[RegisteredModel]:
        """Registered models, newest first."""
        query = select(model_registry).order_by(
            model_registry.c.trained_at.desc(), model_registry.c.version.desc()
        )
        if kind is not None:
            query = query.where(model_registry.c.kind == kind)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [_entry(row._mapping) for row in rows]

    async def load_latest[T](
        self, kind: ModelKind, model_type: type[T]
    ) -> tuple[RegisteredModel, T] | None:
        """The highest version of `kind` and its artifact, or None if none is registered."""
        query = (
            select(model_registry)
            .where(model_registry.c.kind == kind)
            .order_by(model_registry.c.version.desc())
            .limit(1)
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        if row is None:
            return None
        entry = _entry(row._mapping)
        with (self._artifact_dir / entry.artifact_path).open("rb") as artifact:
            model = pickle.load(artifact)
        if not isinstance(model, model_type):
            raise TypeError(f"{entry.artifact_path} holds a {type(model).__name__}")
        return entry, model

    def _save(self, model: object, artifact_path: str) -> None:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        target = self._artifact_dir / artifact_path
        partial = target.with_suffix(".partial")
        with partial.open("wb") as artifact:
            pickle.dump(model, artifact, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(partial, target)


def _entry(row: Any) -> RegisteredModel:
    return RegisteredModel(
        model_id=UUID(str(row["model_id"])),
        kind=ModelKind(row["kind"]),
        version=row["version"],
        trained_at=row["trained_at"],
        as_of_week=row["as_of_week"],
        metrics=dict(row["metrics"]),
        artifact_path=row["artifact_path"],
    )


class LatestModel[T]:
    """The latest registered model of one kind, loaded on first use.

    While none loads (nothing registered yet, the database is down, the artifact is gone),
    every call tries again, so a model trained after the API started is picked up without a
    restart (ADR 0023). Once loaded it stays: a retrain swaps it explicitly.
    """

    def __init__(self, registry: ModelRegistry, kind: ModelKind, model_type: type[T]) -> None:
        self._registry = registry
        self._kind = kind
        self._model_type = model_type
        self._loaded: tuple[RegisteredModel, T] | None = None

    async def get(self) -> tuple[RegisteredModel, T] | None:
        if self._loaded is None:
            try:
                self._loaded = await self._registry.load_latest(self._kind, self._model_type)
            except Exception:
                log.warning("model_registry.load_failed", kind=self._kind.value, exc_info=True)
        return self._loaded

    async def is_loaded(self) -> bool:
        return await self.get() is not None

    def set(self, loaded: tuple[RegisteredModel, T]) -> None:
        """Make a model just registered the live one (a retrain; ADR 0026)."""
        self._loaded = loaded
