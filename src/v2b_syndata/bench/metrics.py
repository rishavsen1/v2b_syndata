"""Post-run metrics from an ACN-Sim simulation + the source v2b CSVs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsResult:
    """Per-scenario evaluation summary.

    Three failure modes are tracked:
    - **admission rejection**: session arrived but no charger free → never plugged in.
      Counted via `n_sessions_rejected` / `admission_rejection_rate`.
    - **charge target miss** (among admitted): plugged in but
      `energy_delivered < energy_requested − epsilon` at departure.
      Counted via `target_miss_rate` (denominator: admitted only).
    - **e2e miss**: union of the two above, denominator = all offered.
      Counted via `e2e_miss_rate`.
    """

    algorithm: str
    scenario_id: str
    seed: int

    # Admission
    n_sessions_offered: int       # total sessions in input
    n_sessions_admitted: int      # plugged in onto a charger
    n_sessions_rejected: int      # arrived but no charger free
    admission_rejection_rate: float  # rejected / offered

    # Energy (over admitted sessions)
    total_kwh_requested: float
    total_kwh_delivered: float
    energy_fulfillment_rate: float  # delivered / requested, [0, 1]

    # Per-admitted-session
    n_sessions_satisfied: int  # delivered ≥ requested - epsilon, among admitted
    target_miss_rate: float    # 1 - n_satisfied / n_admitted

    # End-to-end (counts admission rejection AND charge miss)
    e2e_miss_rate: float       # (rejected + admitted-but-missed) / offered

    # Power
    peak_charge_kw: float        # max aggregate EV charge over sim
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
            "n_sessions_offered": self.n_sessions_offered,
            "n_sessions_admitted": self.n_sessions_admitted,
            "n_sessions_rejected": self.n_sessions_rejected,
            "admission_rejection_rate": self.admission_rejection_rate,
            "total_kwh_requested": self.total_kwh_requested,
            "total_kwh_delivered": self.total_kwh_delivered,
            "energy_fulfillment_rate": self.energy_fulfillment_rate,
            "n_sessions_satisfied": self.n_sessions_satisfied,
            "target_miss_rate": self.target_miss_rate,
            "e2e_miss_rate": self.e2e_miss_rate,
            "peak_charge_kw": self.peak_charge_kw,
            "peak_net_kw": self.peak_net_kw,
            "peak_net_reduction_pct": self.peak_net_reduction_pct,
            "runtime_sec": self.runtime_sec,
        }
