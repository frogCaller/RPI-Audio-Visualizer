#!/usr/bin/env bash
# ------------------------------------------------------------
# setup.sh – One-click environment setup for the Music project
# ------------------------------------------------------------
# Requirements:
#   • bash
#   • python3 + python3-venv (on Debian/Raspbian: sudo apt install python3-venv)
# ------------------------------------------------------------

set -euo pipefail   # Exit on error, undefined var, pipe failure

# ---------- Config ----------
VENV_NAME="Music_env"
REQUIREMENTS=(
    "pillow"
    "mutagen"
    "lgpio"
    "pigpio"
    "gpiozero"
    "flask"
    "requests"
    "pygame"
    "numpy"
    "smbus"
    "spidev"
)
# ----------------------------

# Helper colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log()   { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---------- 1. Check prerequisites ----------
command -v python3 >/dev/null || error "python3 not found – install Python 3 first."
command -v pip3    >/dev/null || warn "pip3 not found – will try to use pip from python."

# ---------- 1.5. System update ----------
if command -v apt-get >/dev/null; then
    log "Updating system packages (sudo apt update)..."
    sudo apt update -y || warn "System update failed — continuing anyway."
else
    warn "apt-get not found — skipping system update."
fi

# ---------- 2. Create virtual environment ----------
if [ -d "$VENV_NAME" ]; then
    log "Virtual environment '$VENV_NAME' already exists – will reuse it."
else
    log "Creating virtual environment '$VENV_NAME' ..."
    python3 -m venv "$VENV_NAME" || error "Failed to create venv. Install python3-venv (apt install python3-venv)."
fi

# Activate it (source the script)
# shellcheck source=/dev/null
source "${VENV_NAME}/bin/activate" || error "Could not activate venv."

# ---------- 3. Upgrade pip ----------
log "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# ---------- 4. Install Python packages ----------
"${VENV_NAME}/bin/pip" install "${REQUIREMENTS[@]}"

# ---------- 5. Optional: system packages for lgpio/pigpio ----------
# (Only needed on Raspberry Pi / Debian-based systems)
if command -v apt-get >/dev/null; then
    if command -v sudo >/dev/null; then
        log "Detected Debian-based system – installing system packages..."
        sudo apt-get update
        sudo apt-get install -y python3-lgpio python3-pigpio pigpio || warn "System packages failed (non-critical)."
    else
        warn "'sudo' not found – skipping system package installs."
    fi
fi

# ---------- 6. Verify installation ----------
log "Verifying installed packages..."
for pkg in "${REQUIREMENTS[@]}"; do
    # Convert to lowercase and replace hyphens
    modname=$(echo "$pkg" | tr '[:upper:]' '[:lower:]' | tr '-' '_')

    # Handle special cases
    case "$modname" in
        pillow) modname="PIL" ;;
        *) ;;
    esac

    python -c "import ${modname}; print('${pkg} OK')" 2>/dev/null || error "Failed to import $pkg"
done

# ---------- 7. Final instructions ----------
log "Setup complete!"
echo
echo "   • Virtual environment: ./${VENV_NAME}"
echo "   • Activate anytime:    source ${VENV_NAME}/bin/activate"
echo "   • Run your app:        python music.py"
echo

# Keep the terminal open if the script was double-clicked
if [[ -t 1 ]]; then
    exec "${SHELL:-/bin/bash}"
fi
