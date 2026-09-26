"""`python -m promopilot.models`: train the demand model on the loaded data and register it.

`make train` fits on the data `make data` loaded into Postgres at DATABASE_URL, as of the
first week after the history unless --as-of-week says otherwise, and saves the artifact
under MODEL_DIR.
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.config import Settings
from promopilot.data import RetailData
from promopilot.models.registry import ModelRegistry
from promopilot.models.training import train_demand_model

DEFAULT_SEED = 42


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.models", description=__doc__)
    parser.add_argument("--as-of-week", type=int, help="defaults to the week after the history")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--model-dir", type=Path, help="defaults to MODEL_DIR")
    parser.add_argument("--database-url", help="defaults to DATABASE_URL")
    args = parser.parse_args(argv)

    settings = Settings()
    engine = create_async_engine(args.database_url or settings.database_url)
    try:
        data = RetailData(engine)
        as_of_week = args.as_of_week
        if as_of_week is None:
            as_of_week = await data.default_as_of_week()
        registry = ModelRegistry(engine, args.model_dir or settings.model_dir)
        started = time.perf_counter()
        entry = await train_demand_model(data, registry, as_of_week=as_of_week, seed=args.seed)
    finally:
        await engine.dispose()
    metrics = ", ".join(f"{name} {value:.3f}" for name, value in entry.metrics.items())
    print(
        f"registered {entry.kind} v{entry.version} (as of week {entry.as_of_week}, seed "
        f"{args.seed}; {metrics}) in {time.perf_counter() - started:.1f}s"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
