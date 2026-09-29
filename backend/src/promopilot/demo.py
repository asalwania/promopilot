"""`python -m promopilot.demo`: the init step of `make demo` (ADR 0073).

Before the api starts, it makes the stack plannable:

1. generate the seed-42 world (the default config) and load it into Postgres, as `make data`
   does, unless the sales history is already loaded;
2. train and register the demand and relations models into MODEL_DIR (the `model-artifacts`
   volume), as `make train` does, unless the latest of each is registered, has its artifact
   on the volume and was trained as of the loaded data's first future week.

Each step says what it does and how long it took, so a first start shows its progress and a
restart skips both steps in seconds. The state is read from Postgres and the volume
themselves, never from a marker file that could disagree with them.
"""

import argparse
import asyncio
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.config import Settings
from promopilot.data import RetailData, load_dataset, migrate
from promopilot.datagen import generate, write
from promopilot.datagen.config import GeneratorConfig, load_config
from promopilot.models.registry import ModelKind, ModelRegistry
from promopilot.models.training import DEFAULT_SEED, train_models


class Demo(Protocol):
    """What the init step reads and does."""

    async def data_loaded(self) -> bool: ...

    async def models_ready(self) -> bool: ...

    async def load_data(self) -> None: ...

    async def train(self) -> None: ...


async def prepare(
    demo: Demo, *, say: Callable[[str], None], clock: Callable[[], float] = time.perf_counter
) -> None:
    """Load the data and train the models, skipping what is already done."""

    async def step(action: Callable[[], Awaitable[None]], doing: str) -> None:
        say(doing)
        started = clock()
        await action()
        say(f"      done in {clock() - started:.0f} s")

    if await demo.data_loaded():
        say("[1/2] The seed-42 world is already loaded: skipped.")
    else:
        await step(
            demo.load_data,
            "[1/2] Generating the seed-42 world and loading it into Postgres (about 1-2 min)...",
        )
    if await demo.models_ready():
        say("[2/2] The models are already trained: skipped.")
    else:
        await step(
            demo.train,
            "[2/2] Training the demand and relations models (about 1-3 min)...",
        )
    say("Demo data and models are ready.")


class PostgresDemo:
    """The data in Postgres and the model artifacts under `model_dir`."""

    def __init__(
        self,
        *,
        database_url: str,
        model_dir: Path,
        config: GeneratorConfig | None = None,
        seed: int | None = None,
    ) -> None:
        self._url = database_url
        self._model_dir = model_dir
        self._config = config
        self._seed = seed

    async def data_loaded(self) -> bool:
        engine = create_async_engine(self._url)
        try:
            # The schema first, so a fresh database can be asked (idempotent).
            await migrate(engine)
            await RetailData(engine).default_as_of_week()
        except LookupError:
            return False
        finally:
            await engine.dispose()
        return True

    async def models_ready(self) -> bool:
        engine = create_async_engine(self._url)
        try:
            try:
                as_of_week = await RetailData(engine).default_as_of_week()
            except LookupError:
                return False
            registry = ModelRegistry(engine, self._model_dir)
            for kind in ModelKind:
                entries = await registry.list(kind)
                if not entries:
                    return False
                latest = max(entries, key=lambda entry: entry.version)
                if latest.as_of_week != as_of_week:
                    return False
                if not (self._model_dir / latest.artifact_path).is_file():
                    return False
        finally:
            await engine.dispose()
        return True

    async def load_data(self) -> None:
        config = self._config or load_config()
        dataset = generate(config, config.seed if self._seed is None else self._seed)
        # Only the tables are loaded; the files, ground truth included, go with the folder.
        with tempfile.TemporaryDirectory(prefix="promopilot-demo-") as folder:
            write(dataset, Path(folder))
            await load_dataset(Path(folder), self._url)

    async def train(self) -> None:
        engine = create_async_engine(self._url)
        try:
            data = RetailData(engine)
            registry = ModelRegistry(engine, self._model_dir)
            await train_models(
                data, registry, as_of_week=await data.default_as_of_week(), seed=DEFAULT_SEED
            )
        finally:
            await engine.dispose()


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.demo", description=__doc__)
    parser.add_argument("--database-url", help="defaults to DATABASE_URL")
    parser.add_argument("--model-dir", type=Path, help="defaults to MODEL_DIR")
    args = parser.parse_args(argv)

    settings = Settings()
    demo = PostgresDemo(
        database_url=args.database_url or settings.database_url,
        model_dir=args.model_dir or settings.model_dir,
    )
    try:
        await prepare(demo, say=lambda line: print(line, flush=True))
    except Exception as error:
        print(f"The demo could not be prepared: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
