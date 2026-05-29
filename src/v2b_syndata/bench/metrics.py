"""Post-run metrics from an ACN-Sim simulation + the source v2b CSVs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsResult:
    """Per-scenario evaluation summary.

    Fields are scalar except `per_session_fulfillment` which is the
    full distribution for downstream histogram figures.
    """

    algorithm: str
    scenario_id: str
    seed: int

    # Energy
    total_kwh_requested: float
    total_kwh_delivered: float
    energy_fulfillment_rate: float  # delivered / requested, [0, 1]

    # Per-session
    n_sessions: int
    n_sessions_satisfied: int  # delivered ≥ requested - epsilon
    target_miss_rate: float    # 1 - n_satisfied / n_sessions

    # Power
    peak_charge_kw: float        # max aggregate charge power over sim
    peak_net_kw: float           # max (building_inflex + building_flex + charge)

    # Defaulted / optional below this line
    peak_net_reduction_pct: float | None = None  # set externally vs uncontrolled
    per_session_fulfillment: list[float] = field(default_factory=list)
    runtime_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "total_kwh_requested": self.total_kwh_requested,
            "total_kwh_delivered": self.total_kwh_delivered,
            "energy_fulfillment_rate": self.energy_fulfillment_rate,
            "n_sessions": self.n_sessions,
            "n_sessions_satisfied": self.n_sessions_satisfied,
            "target_miss_rate": self.target_miss_rate,
            "peak_charge_kw": self.peak_charge_kw,
            "peak_net_kw": self.peak_net_kw,
            "peak_net_reduction_pct": self.peak_net_reduction_pct,
            "runtime_sec": self.runtime_sec,
        }
