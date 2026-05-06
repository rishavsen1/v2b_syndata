"""Subprocess wrapper around the EnergyPlus binary."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .exceptions import EnergyPlusBinaryNotFound, EnergyPlusRunFailed

_LINUX_INSTALL_GLOBS = ("/usr/local/EnergyPlus-*", "/opt/EnergyPlus-*")
_USER_INSTALL_GLOBS = (str(Path.home() / "opt" / "EnergyPlus-*"),)
_MAC_INSTALL_GLOBS = ("/Applications/EnergyPlus-*",)
_WIN_INSTALL_GLOBS = ("C:\\EnergyPlusV*",)

_BIN_NAMES = ("energyplus", "EnergyPlus")


def _check_callable(binary: Path) -> bool:
    """Sanity-check: ``--version`` returns 0. Catches GLIBC mismatches early."""
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _glob_dirs(globs: tuple[str, ...]) -> list[Path]:
    import glob
    out: list[Path] = []
    for g in globs:
        out.extend(Path(p) for p in glob.glob(g) if Path(p).is_dir())
    return sorted(out)


def discover_energyplus() -> Path:
    """Locate a runnable EnergyPlus binary. Raise ``EnergyPlusBinaryNotFound`` on miss.

    Search order:
      1. ``$ENERGYPLUS_PATH`` (directory containing the binary)
      2. ``$ENERGYPLUS_BIN`` (full path to the binary)
      3. ``which energyplus`` / ``which EnergyPlus``
      4. ``/usr/local/EnergyPlus-*``, ``/opt/EnergyPlus-*``, ``~/opt/EnergyPlus-*``
      5. ``/Applications/EnergyPlus-*``
      6. ``C:\\EnergyPlusV*``
    """
    checked: list[str] = []

    env_dir = os.environ.get("ENERGYPLUS_PATH")
    if env_dir:
        for name in _BIN_NAMES:
            candidate = Path(env_dir) / name
            checked.append(str(candidate))
            if candidate.exists() and _check_callable(candidate):
                return candidate

    env_bin = os.environ.get("ENERGYPLUS_BIN")
    if env_bin:
        candidate = Path(env_bin)
        checked.append(str(candidate))
        if candidate.exists() and _check_callable(candidate):
            return candidate

    for name in _BIN_NAMES:
        which = shutil.which(name)
        if which:
            candidate = Path(which)
            checked.append(f"PATH:{which}")
            if _check_callable(candidate):
                return candidate

    for d in _glob_dirs(_LINUX_INSTALL_GLOBS + _USER_INSTALL_GLOBS + _MAC_INSTALL_GLOBS + _WIN_INSTALL_GLOBS):
        for name in _BIN_NAMES:
            candidate = d / name
            checked.append(str(candidate))
            if candidate.exists() and _check_callable(candidate):
                return candidate

    raise EnergyPlusBinaryNotFound(checked or ["(none)"])


def run_energyplus(
    idf_path: Path,
    epw_path: Path,
    output_dir: Path,
    *,
    binary: Path | None = None,
    timeout_sec: int = 1800,
) -> Path:
    """Run EnergyPlus on ``(idf, epw)``. Return path to the meter CSV (eplusmtr.csv)."""
    idf_path = Path(idf_path).resolve()
    epw_path = Path(epw_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bin_path = binary or discover_energyplus()
    cmd = [
        str(bin_path),
        "-w", str(epw_path),
        "-d", str(output_dir),
        "-r",
        str(idf_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_sec, cwd=output_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise EnergyPlusRunFailed(
            f"EnergyPlus timed out after {timeout_sec}s. cmd={cmd}"
        ) from exc

    if result.returncode != 0:
        raise EnergyPlusRunFailed(
            f"EnergyPlus failed (rc={result.returncode}). "
            f"stderr (tail):\n{result.stderr[-1500:]}"
        )

    meter_csv = output_dir / "eplusmtr.csv"
    out_csv = output_dir / "eplusout.csv"
    if meter_csv.exists():
        return meter_csv
    if out_csv.exists():
        return out_csv
    raise EnergyPlusRunFailed(
        f"EnergyPlus produced no CSV in {output_dir}. "
        f"Check err file: {output_dir / 'eplusout.err'}"
    )
