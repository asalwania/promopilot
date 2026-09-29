"""`make demo`'s init step against real Postgres and a model folder (ADR 0073): a fresh stack
loads and trains, a restart skips both, and a model missing from the volume is trained again."""

from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from promopilot.datagen.config import GeneratorConfig
from promopilot.demo import PostgresDemo, prepare

pytestmark = pytest.mark.integration


async def test_a_fresh_stack_is_prepared_once_and_a_restart_skips_both_steps(
    small_config: GeneratorConfig, tmp_path: Path
) -> None:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        demo = PostgresDemo(
            database_url=postgres.get_connection_url(),
            model_dir=tmp_path,
            config=small_config,
            seed=11,
        )
        fresh = (await demo.data_loaded(), await demo.models_ready())
        first: list[str] = []
        await prepare(demo, say=first.append)
        ready = (await demo.data_loaded(), await demo.models_ready())
        again: list[str] = []
        await prepare(demo, say=again.append)
        remove_relations_artifacts(tmp_path)
        without_artifact = await demo.models_ready()

    assert fresh == (False, False)
    assert [line[:5] for line in first if line.startswith("[")] == ["[1/2]", "[2/2]"]
    assert "skipped" not in " ".join(first)
    assert ready == (True, True)
    assert again == [
        "[1/2] The seed-42 world is already loaded: skipped.",
        "[2/2] The models are already trained: skipped.",
        "Demo data and models are ready.",
    ]
    assert without_artifact is False


def remove_relations_artifacts(model_dir: Path) -> None:
    for artifact in model_dir.glob("relations-v*.pkl"):
        artifact.unlink()
