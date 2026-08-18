"""Deterministic per-node, per-car seed sub-streams.

Adding a new node MUST NOT shift the seeds of unrelated nodes. We therefore key
sub-streams off a stable hash of the node name (SHA-256 truncated to 32 bits)
rather than spawn order. Python's built-in `hash()` is salted across processes
and cannot be used.
"""
from __future__ import annotations

import hashlib

import numpy as np


def stable_int(name: str) -> int:
    """Deterministic 32-bit int from a string. Stable across processes / Python versions."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def seed_for_node(global_seed: int, node_name: str) -> np.random.SeedSequence:
    """SeedSequence for a named node. Adding new nodes does not perturb others."""
    return np.random.SeedSequence(
        entropy=global_seed,
        spawn_key=(stable_int(node_name),),
    )


def rng_for_node(global_seed: int, node_name: str) -> np.random.Generator:
    return np.random.default_rng(seed_for_node(global_seed, node_name))


def seed_for_car(global_seed: int, node_name: str, car_id: int) -> np.random.SeedSequence:
    """SeedSequence for (node, car_id). Stable per-car sub-stream."""
    return np.random.SeedSequence(
        entropy=global_seed,
        spawn_key=(stable_int(node_name), int(car_id)),
    )


def rng_for_car(global_seed: int, node_name: str, car_id: int) -> np.random.Generator:
    return np.random.default_rng(seed_for_car(global_seed, node_name, car_id))
