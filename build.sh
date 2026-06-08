#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# e-con DepthVista Helix iToF — Isaac Sim installer (Linux)
#
# ZED-style install: clone the e-con GitHub repo (USDs + the pure-Python
# `econ.itof.menu` extension) and register it with Isaac Sim, so the camera shows
# up under Create -> Sensors -> Camera and Depth Sensors -> e-con on every launch.
#
# Unlike ZED's build.sh there is NOTHING to compile — the extension is pure Python,
# so this script only clones and registers. Registration is done by generating a
# launcher that passes `--ext-folder/--enable`, because editing Isaac Sim 5.1's
# persistent config is unreliable (silently reset; see IsaacSim issues #376/#377).
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

manual_fallback() {
    cat >&2 <<EOF

[FALLBACK] Could not auto-register with Isaac Sim. Register it manually:
  1. Launch Isaac Sim.
  2. Window -> Extensions -> (gear/hamburger) -> add this path to the search paths:
         ${INSTALL_DIR}/exts
  3. In the Third-Party tab, enable: ${EXT_NAME}
  Then: Create -> Sensors -> Camera and Depth Sensors -> e-con
EOF
}

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
ISAACSIM_PATH="${ISAACSIM_PATH:-${ISAAC_SIM_PATH:-}}"
if [ -z "${ISAACSIM_PATH}" ]; then
    # Common explicit locations (Omniverse Launcher pkg + standalone-zip extractions).
    for cand in \
        "${HOME}"/.local/share/ov/pkg/isaac-sim-* \
        "${HOME}"/.local/share/ov/pkg/isaac_sim-* \
        "${HOME}/isaacsim" \
        "${HOME}/isaac-sim" \
        "${HOME}"/[Dd]ownloads/isaacsim \
        "${HOME}"/[Dd]ownloads/isaac-sim* \
        "${HOME}"/*/[Dd]ownloads/isaacsim \
        "${HOME}/ROBOTICS/downloads/isaacsim" \
        /opt/isaacsim \
        /opt/isaac-sim ; do
        if [ -x "${cand}/isaac-sim.sh" ]; then
            ISAACSIM_PATH="${cand}"
            break
        fi
    done
fi
# Last resort: search under $HOME (depth-limited so it stays fast).
if [ -z "${ISAACSIM_PATH}" ]; then
    found="$(find "${HOME}" -maxdepth 5 -name isaac-sim.sh -type f 2>/dev/null | head -n 1)"
    [ -n "${found}" ] && ISAACSIM_PATH="$(dirname "${found}")"
fi

if [ -z "${ISAACSIM_PATH}" ] || [ ! -x "${ISAACSIM_PATH}/isaac-sim.sh" ]; then
    err "Could not find isaac-sim.sh. Set ISAACSIM_PATH=/path/to/isaacsim and re-run."
    manual_fallback
    exit 1
fi
info "Using Isaac Sim at: ${ISAACSIM_PATH}"

# ── 4. Persistent install: extsUser symlink (discovery) + .kit dependency (autoload)
#
# This is the config-bug-proof mechanism. Isaac Sim 5.1's persistent user.config.json
# silently drops ext folders/enabled flags (#376/#377), so we instead:
#   (a) symlink the extension into <isaac>/extsUser — already on the default search path,
#   (b) add it to the Full app's .kit [dependencies] — read fresh from disk each launch and
#       never rewritten by Isaac, exactly how the built-in vendors (Intel/Stereolabs) load.
# Result: the camera appears on every NORMAL launch, no special launcher needed.
EXTSUSER="${ISAACSIM_PATH}/extsUser"
mkdir -p "${EXTSUSER}"
ln -sfn "${EXT_DIR}" "${EXTSUSER}/${EXT_NAME}"
info "Linked ${EXTSUSER}/${EXT_NAME} -> ${EXT_DIR}"

if command -v python3 >/dev/null 2>&1; then
    python3 "${INSTALL_DIR}/scripts/patch_kit.py" "${ISAACSIM_PATH}/apps" "${EXT_NAME}" \
        || err "Could not patch .kit files — the launcher fallback below still works."
else
    info "python3 not found — skipping .kit patch (the launcher below still works)."
fi

# ── 5. Generate a launcher too (works even if the .kit patch was skipped) ─────
LAUNCHER="${INSTALL_DIR}/start-isaacsim-econ.sh"
cat > "${LAUNCHER}" <<EOF
#!/bin/bash
# Auto-generated by build.sh — explicit launch with the e-con extension enabled.
# Normally unnecessary (the .kit dependency auto-loads it), but handy if Isaac Sim
# was reinstalled/updated and you haven't re-run build.sh yet.
exec "${ISAACSIM_PATH}/isaac-sim.sh" \\
    --ext-folder "${INSTALL_DIR}/exts" \\
    --enable "${EXT_NAME}" \\
    "\$@"
EOF
chmod +x "${LAUNCHER}"
info "Wrote launcher: ${LAUNCHER}"

# ── 6. Done ───────────────────────────────────────────────────────────────────
cat <<EOF

[SUCCESS] e-con DepthVista Helix installed (auto-loads on every launch).

  If Isaac Sim is currently OPEN, fully close and reopen it.
  Launch Isaac Sim normally (App Selector / your usual command) — no special command needed.

  Then in the viewport menu:
      Create -> Sensors -> Camera and Depth Sensors -> e-con
          - DepthVista Helix iToF (USB)
          - DepthVista Helix iToF (GMSL)

  (A 'start-isaacsim-econ.sh' launcher was also written as a fallback.)
  Uninstall: rm "${EXTSUSER}/${EXT_NAME}" and restore the apps/*.kit.bak files.
EOF
