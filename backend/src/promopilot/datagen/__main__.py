"""`python -m promopilot.datagen`: generate the synthetic world and write it (`make data`)."""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from promopilot.datagen.config import load_config
from promopilot.datagen.generator import generate
from promopilot.datagen.writer import write


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.datagen", description=__doc__)
    parser.add_argument("--config", type=Path, help="YAML overriding datagen/config.yaml")
    parser.add_argument("--seed", type=int, help="overrides the config seed")
    parser.add_argument("--out", type=Path, default=Path("data"), help="data directory")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
