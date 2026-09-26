"""`python -m promopilot.datagen`: generate the synthetic world, write it, optionally load it.

`make data` runs generate -> write -> load into the Postgres at DATABASE_URL.
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from promopilot.config import Settings
from promopilot.data import load_dataset
from promopilot.datagen.config import load_config
from promopilot.datagen.generator import generate
from promopilot.datagen.writer import write


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.datagen", description=__doc__)
    parser.add_argument("--config", type=Path, help="YAML overriding datagen/config.yaml")
    parser.add_argument("--seed", type=int, help="overrides the config seed")
    parser.add_argument("--out", type=Path, default=Path("data"), help="data directory")
    parser.add_argument("--load", action="store_true", help="load the tables into Postgres")
    parser.add_argument("--database-url", help="defaults to DATABASE_URL")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    config = load_config(args.config)
    seed = config.seed if args.seed is None else args.seed
    dataset = generate(config, seed)
    paths = write(dataset, args.out)
    rows = sum(len(getattr(dataset, name)) for name in paths.tables)
    print(
        f"generated {len(paths.tables)} tables ({rows:,} rows) with seed {seed} "
        f"into {args.out} in {time.perf_counter() - started:.1f}s"
    )
    if args.load:
        started = time.perf_counter()
        await load_dataset(args.out, args.database_url or Settings().database_url)
        print(f"loaded them into Postgres in {time.perf_counter() - started:.1f}s")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
