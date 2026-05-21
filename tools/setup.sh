#!/usr/bin/env bash
#
# One-shot, agent-agnostic install for v2b-syndata.
# Mirrors .claude/commands/setup.md but as a plain shell script — so any
# user (or any agentic CLI: Claude Code, Copilot CLI, Codex, Gemini CLI,
# Cursor, …) can drive it with a single command and no platform-specific
# decision-making on its part.
#
# Idempotent: safe to re-run; skips phases whose post-condition already
# holds. Fails fast on error with a clear message.

set -euo pipefail

EP_VERSION="23.2.0"
EP_TAG="7636e6b3e9"
EP_DIR_NAME="EnergyPlus-23-2-0"
EP_DIR="${HOME}/opt/${EP_DIR_NAME}"
EP_BIN="${EP_DIR}/energyplus"
CACHE="${HOME}/.cache/v2b-syndata"
SMOKE_OUT="/tmp/v2b_setup_smoke"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
fail() { printf "\n\033[31mFAIL:\033[0m %s\n" "$*" >&2; exit 1; }

# ─── Phase 0: sanity ─────────────────────────────────────────────────────
bold ">> phase 0  sanity"
[[ -f pyproject.toml && -d src/v2b_syndata ]] \
  || fail "run from repo root (must contain pyproject.toml and src/v2b_syndata/)"

OS="$(uname -s)"
ARCH="$(uname -m)"
echo "    platform: ${OS}-${ARCH}"

# ─── Phase 1: uv ─────────────────────────────────────────────────────────
bold ">> phase 1  uv"
if command -v uv >/dev/null 2>&1; then
  echo "    found: $(uv --version)"
else
  echo "    installing uv..."
  case "$OS" in
    Linux|Darwin) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    *) fail "auto-install of uv only supported on Linux/macOS; install manually then re-run (see https://astral.sh/uv)" ;;
  esac
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || fail "uv installed but not on PATH; add \$HOME/.local/bin to PATH and re-run"
  echo "    installed: $(uv --version)"
fi

# ─── Phase 2: python deps ─────────────────────────────────────────────────
bold ">> phase 2  uv sync"
uv sync

# ─── Phase 3: EnergyPlus ─────────────────────────────────────────────────
bold ">> phase 3  EnergyPlus"

ep_probe() {
  uv run python -c \
    "from v2b_syndata.load_pipeline.ep_runner import discover_energyplus; print(discover_energyplus())" \
    2>/dev/null
}

ep_version() {
  # Print version string like "23.2.0" from a binary path, or empty on failure.
  local bin="$1"
  [[ -x "${bin}" ]] || { echo ""; return; }
  "${bin}" --version 2>/dev/null \
    | grep -oE "Version [0-9]+\.[0-9]+(\.[0-9]+)?" \
    | head -1 \
    | awk '{print $2}'
}

REQUIRED_EP_MAJOR_MINOR="23.2"
PINNED_OK=0

if EP_PATH="$(ep_probe)" && [[ -n "${EP_PATH}" ]]; then
  EP_VER="$(ep_version "${EP_PATH}")"
  echo "    discovered: ${EP_PATH}  (version: ${EP_VER:-unknown})"
  if [[ "${EP_VER}" == ${REQUIRED_EP_MAJOR_MINOR}* ]]; then
    PINNED_OK=1
  else
    echo "    version mismatch — project IDFs require ${REQUIRED_EP_MAJOR_MINOR}.x"
    echo "    forcing install of ${EP_VERSION} to ${EP_DIR} and overriding ENERGYPLUS_PATH"
  fi
fi

if [[ ${PINNED_OK} -eq 0 ]]; then
  if [[ ! -x "${EP_BIN}" ]]; then
    mkdir -p "${CACHE}" "${HOME}/opt"
    case "${OS}-${ARCH}" in
      Linux-x86_64)
        ASSET="EnergyPlus-${EP_VERSION}-${EP_TAG}-Linux-Ubuntu22.04-x86_64.tar.gz" ;;
      Darwin-arm64)
        ASSET="EnergyPlus-${EP_VERSION}-${EP_TAG}-Darwin-macOS12.1-arm64.tar.gz" ;;
      Darwin-x86_64)
        ASSET="EnergyPlus-${EP_VERSION}-${EP_TAG}-Darwin-macOS12.1-x86_64.tar.gz" ;;
      *)
        fail "unsupported platform ${OS}-${ARCH}; download EnergyPlus ${EP_VERSION} manually and set ENERGYPLUS_PATH=/path/to/install" ;;
    esac
    URL="https://github.com/NREL/EnergyPlus/releases/download/v${EP_VERSION}/${ASSET}"
    DEST="${CACHE}/${ASSET}"
    if [[ ! -f "${DEST}" ]]; then
      echo "    downloading ${ASSET}..."
      curl -fL --retry 3 --retry-delay 2 -o "${DEST}" "${URL}" \
        || fail "download failed: ${URL}"
    fi
    echo "    extracting..."
    tar -xzf "${DEST}" -C "${HOME}/opt/"
    extracted="$(find "${HOME}/opt" -maxdepth 1 -type d -name "EnergyPlus-${EP_VERSION}*" | head -1)"
    [[ -n "${extracted}" ]] || fail "tarball extracted but expected directory not found under \$HOME/opt"
    if [[ "${extracted}" != "${EP_DIR}" ]]; then
      rm -rf "${EP_DIR}"
      mv "${extracted}" "${EP_DIR}"
    fi
  fi
  export ENERGYPLUS_PATH="${EP_DIR}"
  EP_PATH="$(ep_probe)" \
    || fail "EnergyPlus installed at ${EP_DIR} but discover_energyplus() still fails. Add 'export ENERGYPLUS_PATH=${EP_DIR}' to your shell rc and re-run."
  EP_VER="$(ep_version "${EP_PATH}")"
  echo "    installed: ${EP_PATH}  (version: ${EP_VER:-unknown})"
  echo
  echo "    NOTE: this shell now has ENERGYPLUS_PATH=${EP_DIR}, but new shells"
  echo "          will fall back to any system EnergyPlus on PATH. To make"
  echo "          the pin permanent, add this to your ~/.bashrc or ~/.zshrc:"
  echo "              export ENERGYPLUS_PATH=${EP_DIR}"
  echo
fi

# ─── Phase 4: smoke generation ───────────────────────────────────────────
bold ">> phase 4  smoke generation (S01, seed=42)"
rm -rf "${SMOKE_OUT}"
uv run python -m v2b_syndata.cli generate \
  --scenario S01 --seed 42 --output-dir "${SMOKE_OUT}/" >/dev/null
EXPECTED=(building_load.csv cars.csv users.csv chargers.csv grid_prices.csv dr_events.csv sessions.csv manifest.json)
for f in "${EXPECTED[@]}"; do
  [[ -e "${SMOKE_OUT}/${f}" ]] || fail "smoke output missing: ${f}"
done
rm -rf "${SMOKE_OUT}"
echo "    OK — all 7 CSVs + manifest.json emitted"

# ─── Phase 5: report ─────────────────────────────────────────────────────
echo
bold "setup complete"
printf "%-16s %-8s %s\n" "component"   "status" "detail"
printf "%-16s %-8s %s\n" "uv"          "OK"     "$(uv --version | awk '{print $2}')"
printf "%-16s %-8s %s\n" "python deps" "OK"     "uv sync clean"
printf "%-16s %-8s %s\n" "EnergyPlus"  "OK"     "${EP_PATH}"
printf "%-16s %-8s %s\n" "smoke gen"   "OK"     "S01 seed=42 → 7 CSVs + manifest"
echo
echo "Next: 'uv run python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir data/output/dev/S01/seed42/'"
