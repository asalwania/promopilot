"""Named random streams: one explicit seed, one independent child stream per concern.

A stream's seed depends only on the root seed and its name, so adding a new concern (or
drawing more numbers in one) never reshuffles the others.
"""

import zlib

import numpy as np


def stream(seed: int, name: str) -> np.random.Generator:
    key = zlib.crc32(name.encode("utf-8"))
    return np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(key,)))
