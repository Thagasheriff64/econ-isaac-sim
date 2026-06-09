#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# e-con DepthVista Helix iToF — Isaac Sim uninstaller (Linux)
#
# Reverts EVERYTHING build.sh did, returning Isaac Sim to stock:
#   - restores the Full app .kit files from their .bak (removes the dependency line),
#   - removes the extension from <isaac>/extsUser.
# Same Isaac-Sim detection as build.sh: env -> common locations -> search $HOME -> ask.
#
# Usage:
#   ./uninstall.sh                          # auto-detect Isaac Sim
#   ISAACSIM_PATH=/path/to/isaacsim ./uninstall.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_NAME="${EXT_NAME:-econ.itof.menu}"
info() { printf '[INFO] %s\n'  "$*"; }
err()  { printf '[ERROR] %s\n' "$*" >&2; }

# ── Locate Isaac Sim (identical logic to build.sh) ────────────────────────────
ISAACSIM_PATH="${ISAACSIM_PATH:-${ISAAC_SIM_PATH:-}}"
if [ -z "${ISAACSIM_PATH}" ]; then
    for cand in \
        "${HOME}"/.local/share/ov/pkg/isaac-sim-* \
        "${HOME}"/.local/share/ov/pkg/isaac_sim-* \
        "${HOME}/isaacsim" "${HOME}/isaac-sim" \
        "${HOME}"/[Dd]ownloads/isaacsim "${HOME}"/[Dd]ownloads/isaac-sim* \
        /opt/isaacsim /opt/isaac-sim ; do
        if [ -x "${cand}/isaac-sim.sh" ]; then ISAACSIM_PATH="${cand}"; break; fi
    done
fi
if [ -z "${ISAACSIM_PATH}" ]; then
    info "Searching for isaac-sim.sh under ${HOME} …"
    # Prune Trash/.cache; -print -quit avoids the SIGPIPE a `| head` would cause under pipefail.
    found="$(find "${HOME}" -maxdepth 7 -type d \( -name Trash -o -name .cache \) -prune \
                 -o -type f -name isaac-sim.sh -print -quit 2>/dev/null || true)"
    [ -n "${found}" ] && ISAACSIM_PATH="$(dirname "${found}")"
fi
while [ -z "${ISAACSIM_PATH}" ] || [ ! -x "${ISAACSIM_PATH}/isaac-sim.sh" ]; do
    if [ ! -t 0 ]; then
        err "Isaac Sim not found. Re-run with: ISAACSIM_PATH=/path/to/isaacsim ./uninstall.sh"
        exit 1
    fi
    printf "Enter the Isaac Sim folder (contains isaac-sim.sh), or blank to abort: "
    read -r ISAACSIM_PATH
    [ -z "${ISAACSIM_PATH}" ] && { err "Aborted."; exit 1; }
    ISAACSIM_PATH="${ISAACSIM_PATH/#\~/$HOME}"
    [ -x "${ISAACSIM_PATH}/isaac-sim.sh" ] || err "No isaac-sim.sh in '${ISAACSIM_PATH}' — try again."
done
info "Using Isaac Sim at: ${ISAACSIM_PATH}"

# ── Revert ────────────────────────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
    python3 "${SCRIPT_DIR}/scripts/patch_kit.py" "${ISAACSIM_PATH}/apps" "${EXT_NAME}" --uninstall \
        || err "Could not restore .kit files (continuing to remove the extension)."
else
    err "python3 not found — cannot restore .kit files automatically."
fi

rm -rf "${ISAACSIM_PATH}/extsUser/${EXT_NAME}"
info "Removed ${ISAACSIM_PATH}/extsUser/${EXT_NAME}"

cat <<EOF

[SUCCESS] e-con DepthVista Helix removed. Isaac Sim is back to stock.
  Re-install anytime with ./build.sh
EOF
