"""Write calibrated parameters back to populations.yaml as overlay block.

Uses ruamel.yaml to preserve comments and ordering of the source file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


def write_region_distributions(
    populations_path: Path,
    population_name: str,
    region_fits: dict[str, dict[str, Any]],
    calibration_metadata: dict[str, Any],
    axes_weights: dict[str, float] | None = None,
) -> None:
    """Add or replace `region_distributions` and `calibration_metadata` blocks
    on a single population entry. Preserves all other content + comments.

    When ``axes_weights`` (region_name → weight) is provided, the matching
    ``axes_distribution[*].weight`` fields are overwritten in place with the
    calibrated values, so generation's per-region frequency (per_entity.py reads
    this single field) tracks the empirical user share instead of a stale
    hand-authored placeholder. Bounds and ordering are untouched.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    with populations_path.open() as f:
        data = yaml.load(f)

    if population_name not in data:
        raise KeyError(f"population {population_name!r} not in {populations_path}")

    pop = data[population_name]
    pop["region_distributions"] = _to_commented(region_fits)
    pop["calibration_metadata"] = _to_commented(calibration_metadata)

    if axes_weights is not None:
        for region in pop.get("axes_distribution", []):
            name = region.get("name")
            if name in axes_weights:
                region["weight"] = round(float(axes_weights[name]), 6)

    with populations_path.open("w") as f:
        yaml.dump(data, f)


def _to_commented(obj: Any) -> Any:
    """Recursively convert plain dicts/lists to ruamel CommentedMap so they
    round-trip cleanly. Floats and other primitives pass through.
    """
    if isinstance(obj, dict):
        cm = CommentedMap()
        for k, v in obj.items():
            cm[k] = _to_commented(v)
        return cm
    if isinstance(obj, list):
        return [_to_commented(x) for x in obj]
    return obj
