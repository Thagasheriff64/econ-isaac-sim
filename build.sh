#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# e-con DepthVista Helix iToF — Isaac Sim installer (Linux)
#
# Clones/verifies the repo, locates Isaac Sim, and registers the econ.itof.menu extension
# so the cameras appear under Create -> Sensors -> Camera and Depth Sensors -> e-con on
# every launch. Pure Python — nothing to compile.
#
# Usage:
#   ./build.sh                         # clone (if needed) + register
#   ./build.sh <repo-url>              # override REPO_URL
#   REPO_URL=… INSTALL_DIR=… ISAACSIM_PATH=… ./build.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Configuration (override via env or 1st arg) ───────────────────────────────
REPO_URL="${REPO_URL:-${1:-https://github.com/Thagasheriff64/econ-isaac-sim.git}}"
EXT_NAME="${EXT_NAME:-econ.itof.menu}"

# If this script already lives inside a clone (exts/<EXT_NAME> present beside it),
# install in place; otherwise clone into ~/econ-isaac-sim.
if [ -d "${SCRIPT_DIR}/exts/${EXT_NAME}" ]; then
    INSTALL_DIR="${INSTALL_DIR:-${SCRIPT_DIR}}"
else
    INSTALL_DIR="${INSTALL_DIR:-${HOME}/econ-isaac-sim}"
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { printf '[INFO] %s\n'  "$*"; }
err()   { printf '[ERROR] %s\n' "$*" >&2; }

# ── 1. Clone or update the repo ───────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
    err "git is not installed. Install git and re-run."
    exit 1
fi

if [ -d "${INSTALL_DIR}/.git" ]; then
    info "Updating existing clone at ${INSTALL_DIR} …"
    git -C "${INSTALL_DIR}" pull --ff-only || info "git pull skipped (local changes?) — continuing."
elif [ -d "${INSTALL_DIR}/exts/${EXT_NAME}" ]; then
    info "Running from inside the repo at ${INSTALL_DIR} — skipping clone."
else
    info "Cloning ${REPO_URL} -> ${INSTALL_DIR} …"
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

# ── 2. Sanity-check the extension is present (do NOT build anything) ──────────
EXT_DIR="${INSTALL_DIR}/exts/${EXT_NAME}"
if [ ! -d "${EXT_DIR}" ]; then
    err "Extension not found at ${EXT_DIR}."
    err "The cloned repo must contain exts/${EXT_NAME}/ (config/extension.toml + python)."
    exit 1
fi
info "Found extension: ${EXT_DIR}"

# ── 3. Locate the Isaac Sim install (holds isaac-sim.sh) ──────────────────────
# Detection order: $ISAACSIM_PATH/$ISAAC_SIM_PATH env -> common locations -> search $HOME ->
# ask the user.  No path is hard-coded to one machine.
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
    # Prune Trash/.cache (a trashed Isaac copy must not be picked). -print -quit stops at
    # the first real match without a pipe (`| head` would SIGPIPE and trip pipefail);
    # `|| true` guards the no-match case.
    found="$(find "${HOME}" -maxdepth 7 -type d \( -name Trash -o -name .cache \) -prune \
                 -o -type f -name isaac-sim.sh -print -quit 2>/dev/null || true)"
    [ -n "${found}" ] && ISAACSIM_PATH="$(dirname "${found}")"
fi
# Still nothing -> ask the user (interactive only).
while [ -z "${ISAACSIM_PATH}" ] || [ ! -x "${ISAACSIM_PATH}/isaac-sim.sh" ]; do
    if [ ! -t 0 ]; then
        err "Isaac Sim not found. Re-run with: ISAACSIM_PATH=/path/to/isaacsim ./build.sh"
        exit 1
    fi
    printf "Enter the Isaac Sim folder (contains isaac-sim.sh), or blank to abort: "
    read -r ISAACSIM_PATH
    [ -z "${ISAACSIM_PATH}" ] && { err "Aborted — no Isaac Sim path given."; exit 1; }
    ISAACSIM_PATH="${ISAACSIM_PATH/#\~/$HOME}"
    [ -x "${ISAACSIM_PATH}/isaac-sim.sh" ] || err "No isaac-sim.sh in '${ISAACSIM_PATH}' — try again."
done
info "Using Isaac Sim at: ${ISAACSIM_PATH}"

# ── 4. Register so it auto-loads on every normal launch ──────────────────────
#   (a) symlink the extension into <isaac>/extsUser  (already on the search path), and
#   (b) add it to the Full app's .kit [dependencies]  (read fresh each launch, never rewritten;
#       the persistent user config is unreliable on Isaac Sim 5.1).
EXTSUSER="${ISAACSIM_PATH}/extsUser"
mkdir -p "${EXTSUSER}"
ln -sfn "${EXT_DIR}" "${EXTSUSER}/${EXT_NAME}"
info "Linked ${EXTSUSER}/${EXT_NAME}"

if command -v python3 >/dev/null 2>&1; then
    python3 "${INSTALL_DIR}/scripts/patch_kit.py" "${ISAACSIM_PATH}/apps" "${EXT_NAME}" \
        || { err "Could not patch the Isaac Sim .kit files."; exit 1; }
else
    err "python3 not found — needed to register the extension. Install python3 and re-run."
    exit 1
fi

# ── 5. Done ───────────────────────────────────────────────────────────────────
cat <<EOF

[SUCCESS] e-con DepthVista Helix installed (auto-loads on every launch).

  If Isaac Sim is open, fully close and reopen it. Launch normally — no special command.
  Then: Create -> Sensors -> Camera and Depth Sensors -> e-con
          - DepthVista Helix iToF (USB)
          - DepthVista Helix iToF (GMSL)

  Uninstall (reverts everything): ./uninstall.sh
EOF
