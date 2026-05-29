"""V2B benchmarking harness built on ACN-Sim.

Thin adapter that maps v2b_syndata scenario CSVs into an ACN-Sim
ChargingNetwork + EventQueue, runs one of the stock scheduling
algorithms, and emits a MetricsResult.

Scope (v1):
- V1G only. Charger negative min_rate (V2B discharge) is clipped to 0.
- 1:1 car→station mapping. No charger-pool assignment problem.
- Building load + DR aggregated post-hoc into net-load metrics; not
  injected into the scheduler's capacity constraint.
"""
from __future__ import annotations

from .metrics import MetricsResult
from .runner import ALGORITHMS, available_algorithms, run_scenario

__all__ = [
    "MetricsResult",
    "ALGORITHMS",
    "available_algorithms",
    "run_scenario",
]
