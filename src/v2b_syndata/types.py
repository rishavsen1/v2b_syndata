"""Core dataclasses passed between samplers and renderers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class KnobValue:
    """A single resolved knob with its provenance."""
    value: Any
    source: str  # "explicit" | "descriptor:<name>" | "default"


@dataclass
class ResolvedKnobs:
    """All knobs after resolution chain. Indexed by dotted path (e.g. 'ev_fleet.ev_count')."""
    values: dict[str, KnobValue] = field(default_factory=dict)

    def get(self, path: str) -> Any:
        return self.values[path].value

    def source(self, path: str) -> str:
        return self.values[path].source

    def has(self, path: str) -> bool:
        return path in self.values

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {k: {"value": v.value, "source": v.source} for k, v in self.values.items()}


@dataclass
class RootBundle:
    """Tier 1 roots packed into a single struct."""
    C: str  # climate label
    W: dict[str, Any]  # weather config (lat, lon, year)
    A: str  # archetype
    S: str  # size
    O: str  # occupancy_source  # noqa: E741
    T: dict[str, Any]  # tariff config
    U: dict[str, Any]  # population spec (axes_distribution, negotiation_mix, w_multiplier, menu)
    F: dict[str, Any]  # fleet spec
    X: dict[str, Any]  # charger config


@dataclass
class UserAttrs:
    """Per-user assignments produced by A_user."""
    car_id: int
    region: str
    phi: float
    kappa: float
    delta_km: float
    negotiation_type: str
    w1: float
    w2: float


@dataclass
class FleetAttrs:
    """Per-vehicle assignments produced by A_fleet."""
    car_id: int
    battery_class: str
    capacity_kwh: float
    min_allowed_soc: float
    max_allowed_soc: float


@dataclass
class ScenarioContext:
    """Everything a sampler needs."""
    scenario_id: str
    seed: int
    knobs: ResolvedKnobs
    roots: RootBundle | None = None
    a_user: dict[int, UserAttrs] | None = None
    a_fleet: dict[int, FleetAttrs] | None = None
    sim_start: datetime | None = None
    sim_end: datetime | None = None
    # Latents and renderer outputs accumulate as samplers run
    latents: dict[str, Any] = field(default_factory=dict)
    rendered: dict[str, Any] = field(default_factory=dict)
    # Noise resolved per profile
    noise: dict[str, float] = field(default_factory=dict)
    noise_profile_name: str = "clean"

    def datetime_index(self):
        """15-minute datetime index over sim window."""
        import pandas as pd
        return pd.date_range(self.sim_start, self.sim_end, freq="15min", inclusive="left")
