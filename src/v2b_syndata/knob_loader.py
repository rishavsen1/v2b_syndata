"""Knob registry loading + resolution chain.

Resolution priority (highest to lowest):
  1. CLI override (--override path=value)
  2. Scenario YAML overrides[knob_path]
  3. Descriptor expansion (Tier 0 library lookup)
  4. knobs.yaml default

Two override channels:
  - Registry channel: paths in knobs.yaml (e.g. "ev_fleet.ev_count").
  - Deep channel: paths under a prefix in DEEP_OVERRIDE_PREFIXES (e.g.
    "user_behavior.region_distributions.<region>.<dist>.<param>"). Validated
    against per-prefix range table (DIST_PARAM_RANGES). Calibrated leaves
    propagated by descriptor_loader carry source="calibration:<provenance>".
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .types import KnobValue, ResolvedKnobs


class KnobValidationError(ValueError):
    pass


# Per-distribution-parameter range table for deep-channel override validation.
# Lives here (not in validate.py) to avoid circular import — validate.py
# already imports from knob_loader.
DIST_PARAM_RANGES: dict[str, tuple[float, float]] = {
    # Arrival window widened [6,20] → [4,22] (KDD task 6); see ARRIVAL_LO/HI in
    # distribution_fitter. trunc_lo/trunc_hi carry the per-region window so
    # generation reads it back; bounds chosen to admit the [4,22] support.
    "arrival.mu": (4.0, 22.0),
    "arrival.sigma": (0.01, 6.0),
    "arrival.trunc_lo": (0.0, 24.0),
    "arrival.trunc_hi": (0.0, 24.0),
    # Optional 2-component arrival mixture (bimodal commute + midday). Present
    # only when calibration selects a mixture; w2 = 1 - w1. Single TruncNorm
    # (mu/sigma above) remains the default.
    "arrival.w1": (0.0, 1.0),
    "arrival.mu1": (4.0, 22.0),
    "arrival.sigma1": (0.01, 6.0),
    "arrival.mu2": (4.0, 22.0),
    "arrival.sigma2": (0.01, 6.0),
    "dwell.k": (0.01, 5.0),
    "dwell.lambda": (0.01, 24.0),
    # Optional 2-component Weibull dwell mixture (short top-up + long workday).
    # Present only when calibration selects a mixture; w2 = 1 - w1. Single
    # Weibull (k/lambda above) remains the default.
    "dwell.w1": (0.0, 1.0),
    "dwell.k1": (0.01, 5.0),
    "dwell.lambda1": (0.01, 24.0),
    "dwell.k2": (0.01, 5.0),
    "dwell.lambda2": (0.01, 24.0),
    "soc_arrival.alpha": (0.01, 50.0),
    "soc_arrival.beta": (0.01, 50.0),
    "soc_depart.alpha": (0.01, 50.0),
    "soc_depart.beta": (0.01, 50.0),
    "copula.rho_gaussian": (-0.99, 0.99),
}

# Prefix → range table. Add additional deep-override domains here as new
# population-data sub-blocks become overridable.
DEEP_OVERRIDE_PREFIXES: dict[str, dict[str, tuple[float, float]]] = {
    "user_behavior.region_distributions": DIST_PARAM_RANGES,
}


def _match_deep_prefix(path: str) -> tuple[str, str] | None:
    """If path matches a deep prefix, return (prefix, trailing). Else None.

    Example: "user_behavior.region_distributions.stable_commuter.dwell.lambda"
      → ("user_behavior.region_distributions", "dwell.lambda")
    """
    for prefix in DEEP_OVERRIDE_PREFIXES:
        if path.startswith(prefix + "."):
            tail = path[len(prefix) + 1:]
            # tail = "<region>.<dist>.<param>" — last two segments are dist.param.
            parts = tail.split(".")
            if len(parts) < 3:
                return None
            leaf = ".".join(parts[-2:])
            return prefix, leaf
    return None


def _check_deep_range(path: str, value: Any) -> None:
    """Validate a deep-channel override value against its declared range."""
    m = _match_deep_prefix(path)
    if m is None:
        raise KnobValidationError(f"{path}: not a recognized deep-override path")
    prefix, leaf = m
    ranges = DEEP_OVERRIDE_PREFIXES[prefix]
    if leaf not in ranges:
        raise KnobValidationError(
            f"{path}: leaf {leaf!r} not in {prefix} range table; "
            f"valid leaves: {sorted(ranges)}"
        )
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise KnobValidationError(f"{path}: deep override expects numeric, got {type(value).__name__}")
    lo, hi = ranges[leaf]
    v = float(value)
    if not (lo <= v <= hi):
        raise KnobValidationError(f"{path}: {v} outside range [{lo}, {hi}]")


def load_knob_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Load knobs.yaml; return flat dict path -> spec dict."""
    with path.open() as f:
        raw = yaml.safe_load(f)
    flat: dict[str, dict[str, Any]] = {}
    for bucket, knobs in raw.items():
        for name, spec in knobs.items():
            flat[f"{bucket}.{name}"] = spec
    return flat


def all_knob_paths(registry: dict[str, dict[str, Any]]) -> list[str]:
    return list(registry.keys())


def _check_type_and_range(path: str, value: Any, spec: dict[str, Any]) -> None:
    """Validate a value against the knobs.yaml type / range / choices spec."""
    typ = spec.get("type")
    if value is None:
        # null defaults are allowed (e.g. sim_window.custom_start)
        if spec.get("default", "<sentinel>") is None:
            return
        raise KnobValidationError(f"{path}: null value but knob default is non-null")

    if typ == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise KnobValidationError(f"{path}: expected int, got {type(value).__name__}")
        rng = spec.get("range")
        if rng and not (rng[0] <= value <= rng[1]):
            raise KnobValidationError(f"{path}: {value} outside range {rng}")
    elif typ == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise KnobValidationError(f"{path}: expected float, got {type(value).__name__}")
        rng = spec.get("range")
        if rng and not (rng[0] <= float(value) <= rng[1]):
            raise KnobValidationError(f"{path}: {value} outside range {rng}")
    elif typ == "bool":
        if not isinstance(value, bool):
            raise KnobValidationError(f"{path}: expected bool, got {type(value).__name__}")
    elif typ == "categorical":
        choices = spec.get("choices", [])
        if value not in choices:
            raise KnobValidationError(f"{path}: {value!r} not in {choices}")
    elif typ == "simplex":
        if not isinstance(value, (list, tuple)):
            raise KnobValidationError(f"{path}: expected list, got {type(value).__name__}")
        components = spec.get("components", [])
        if len(value) != len(components):
            raise KnobValidationError(f"{path}: expected {len(components)} components, got {len(value)}")
        s = float(sum(value))
        if abs(s - 1.0) > 1e-6:
            raise KnobValidationError(f"{path}: simplex must sum to 1.0, got {s}")
        if any(x < 0 for x in value):
            raise KnobValidationError(f"{path}: simplex entries must be non-negative")
    elif typ == "vec2":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise KnobValidationError(f"{path}: expected length-2 vector")
        rng = spec.get("range")
        if rng:
            for i, v in enumerate(value):
                if not (rng[i][0] <= v <= rng[i][1]):
                    raise KnobValidationError(f"{path}: component {i}={v} outside range {rng[i]}")
    elif typ == "list[vec2]":
        if not isinstance(value, list):
            raise KnobValidationError(f"{path}: expected list of vec2")
        for entry in value:
            if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
                raise KnobValidationError(f"{path}: entry {entry!r} not a vec2")
    elif typ == "list[region]":
        if not isinstance(value, list) or not value:
            raise KnobValidationError(f"{path}: expected non-empty list of regions")
        total = 0.0
        for entry in value:
            for k in ("name", "freq", "consist", "dist_km", "weight"):
                if k not in entry:
                    raise KnobValidationError(f"{path}: region missing {k!r}")
            total += float(entry["weight"])
        if abs(total - 1.0) > 1e-6:
            raise KnobValidationError(f"{path}: region weights must sum to 1.0, got {total}")
    elif typ == "timestamp":
        # null, ISO string, or date/datetime (YAML parses 'YYYY-MM-DD' to date).
        import datetime as _dt
        if value is not None and not isinstance(value, (str, _dt.date, _dt.datetime)):
            raise KnobValidationError(f"{path}: timestamp must be ISO string, date, datetime, or null")
    elif typ == "path":
        if not isinstance(value, str):
            raise KnobValidationError(f"{path}: expected string path")
    # Unknown types pass through


def parse_override_value(raw: str) -> Any:
    """Parse a CLI override string `--override key=value`. Tries YAML first, then string."""
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


# Allow arbitrary depth: bucket.knob[.sub.sub...]=value
_OVERRIDE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)=(.*)$")


def parse_overrides(items: list[str]) -> dict[str, Any]:
    """Parse list of `key.path=yaml_value` into a dict. Uses YAML for value parsing."""
    out: dict[str, Any] = {}
    for s in items:
        m = _OVERRIDE_RE.match(s)
        if not m:
            raise KnobValidationError(f"override {s!r} not in form 'bucket.knob=value'")
        path, raw = m.group(1), m.group(2)
        out[path] = _normalize(parse_override_value(raw))
    return out


def resolve_knobs(
    registry: dict[str, dict[str, Any]],
    descriptor_values: dict[str, tuple[Any, str]],
    scenario_overrides: dict[str, Any],
    cli_overrides: dict[str, Any],
) -> ResolvedKnobs:
    """Apply resolution chain to every knob in registry, plus deep-channel paths.

    `descriptor_values[path] = (value, descriptor_name_or_calibration_source)`.
    If the second tuple element starts with "calibration:" it is stamped as the
    source verbatim (e.g. "calibration:acn_data_2019_2021_20260506"); else it
    becomes "descriptor:<name>".
    """
    resolved = ResolvedKnobs()
    for path, spec in registry.items():
        if path in cli_overrides:
            v = cli_overrides[path]
            src = "explicit"
        elif path in scenario_overrides:
            v = scenario_overrides[path]
            src = "explicit"
        elif path in descriptor_values:
            v, name = descriptor_values[path]
            if name.startswith("calibration:") or name.startswith("hand_specified:"):
                src = name
            else:
                src = f"descriptor:{name}"
        else:
            v = spec.get("default")
            src = "default"
        v = _normalize(v)
        _check_type_and_range(path, v, spec)
        resolved.values[path] = KnobValue(value=v, source=src)

    # Deep-channel paths from descriptors (calibrated population leaves).
    deep_paths_from_descriptors = {
        p for p in descriptor_values if _match_deep_prefix(p) is not None
    }
    # Plus any deep-channel CLI/scenario overrides (allowed even if no descriptor leaf).
    deep_paths_from_overrides = {
        p for p in list(cli_overrides) + list(scenario_overrides)
        if _match_deep_prefix(p) is not None
    }
    all_deep = sorted(deep_paths_from_descriptors | deep_paths_from_overrides)
    for path in all_deep:
        if path in cli_overrides:
            v = cli_overrides[path]
            src = "explicit"
        elif path in scenario_overrides:
            v = scenario_overrides[path]
            src = "explicit"
        else:
            v, name = descriptor_values[path]
            if name.startswith("calibration:") or name.startswith("hand_specified:"):
                src = name
            else:
                src = f"descriptor:{name}"
        v = _normalize(v)
        _check_deep_range(path, v)
        resolved.values[path] = KnobValue(value=float(v), source=src)

    # Reject unknown overrides — must be in registry OR match a deep prefix.
    for path in cli_overrides:
        if path not in registry and _match_deep_prefix(path) is None:
            raise KnobValidationError(f"unknown knob in CLI override: {path}")
    for path in scenario_overrides:
        if path not in registry and _match_deep_prefix(path) is None:
            raise KnobValidationError(f"unknown knob in scenario override: {path}")
    return resolved


def _normalize(v: Any) -> Any:
    """Recursively coerce tuples → lists, dates → ISO strings.

    Stable equality + YAML / JSON round-trip require Python primitives.
    """
    import datetime as _dt
    if isinstance(v, tuple):
        return [_normalize(x) for x in v]
    if isinstance(v, list):
        return [_normalize(x) for x in v]
    if isinstance(v, dict):
        return {k: _normalize(x) for k, x in v.items()}
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v
