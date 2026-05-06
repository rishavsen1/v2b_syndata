"""Hash-keyed parquet cache for EnergyPlus simulation results."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

CACHE_ENV = "V2B_LOAD_CACHE_DIR"


def _cache_root() -> Path:
    import os
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "load_pipeline_cache"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_series(series: pd.Series) -> str:
    h = hashlib.sha256()
    # Hash both the integer ns timestamps and float64 values for byte stability.
    h.update(series.index.asi8.tobytes())
    h.update(series.to_numpy(dtype="float64").tobytes())
    return h.hexdigest()


def cache_key(
    idf_path: Path,
    epw_path: Path,
    occupancy: pd.Series,
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
    extra: str = "",
) -> str:
    """SHA-256 over (idf, epw, occupancy, sim_window). Deterministic per inputs."""
    h = hashlib.sha256()
    h.update(_hash_file(idf_path).encode())
    h.update(_hash_file(epw_path).encode())
    h.update(_hash_series(occupancy).encode())
    h.update(pd.Timestamp(sim_window_start).isoformat().encode())
    h.update(pd.Timestamp(sim_window_end).isoformat().encode())
    if extra:
        h.update(extra.encode())
    return h.hexdigest()


def _key_dir(key: str) -> Path:
    return _cache_root() / key


def get_cached(key: str) -> tuple[pd.Series, pd.Series] | None:
    d = _key_dir(key)
    flex_p = d / "l_flex.parquet"
    inflex_p = d / "l_inflex.parquet"
    if not (flex_p.exists() and inflex_p.exists()):
        return None
    flex = pd.read_parquet(flex_p)["value"]
    flex.name = "L_flex"
    inflex = pd.read_parquet(inflex_p)["value"]
    inflex.name = "L_inflex"
    return flex, inflex


def put_cached(key: str, l_flex: pd.Series, l_inflex: pd.Series) -> None:
    d = _key_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"value": l_flex}).to_parquet(d / "l_flex.parquet")
    pd.DataFrame({"value": l_inflex}).to_parquet(d / "l_inflex.parquet")
