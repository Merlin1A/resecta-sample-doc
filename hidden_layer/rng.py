"""Deterministic integer streams (SplitMix64), the same values on every platform.

Every random choice in this family (ground noise, per-word jitter) is drawn from here, never from
``random`` or a NumPy ``Generator``, whose streams are not promised to stay fixed across versions.
"""

from __future__ import annotations

import numpy as np

_GOLDEN = 0x9E3779B97F4A7C15
_MIX1 = 0xBF58476D1CE4E5B9
_MIX2 = 0x94D049BB133111EB
_MASK = 0xFFFFFFFFFFFFFFFF


def splitmix64(seed: int, n: int) -> np.ndarray:
    """``n`` 64-bit words of the SplitMix64 stream seeded with ``seed`` (uint64 array)."""
    k = np.arange(1, n + 1, dtype=np.uint64)
    with np.errstate(over="ignore"):
        z = np.uint64(seed & _MASK) + k * np.uint64(_GOLDEN)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(_MIX1)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(_MIX2)
        return z ^ (z >> np.uint64(31))


def uniform_ints(seed: int, n: int, lo: int, hi: int) -> np.ndarray:
    """``n`` integers in ``[lo, hi]`` (inclusive), as int64. Modulo reduction: the tiny bias is
    irrelevant here and the values are exact."""
    span = np.uint64(hi - lo + 1)
    return (splitmix64(seed, n) % span).astype(np.int64) + lo


def scalar_ints(seed: int, n: int, lo: int, hi: int) -> list[int]:
    """The same as :func:`uniform_ints`, as a plain list of Python ints."""
    return [int(v) for v in uniform_ints(seed, n, lo, hi)]


def mix_seed(*parts: int | str) -> int:
    """A stable 64-bit seed from a tuple of ints and ASCII strings (FNV-1a over their text form)."""
    h = 0xCBF29CE484222325
    for part in parts:
        for byte in f"{part}|".encode("ascii"):
            h ^= byte
            h = (h * 0x100000001B3) & _MASK
    return h
