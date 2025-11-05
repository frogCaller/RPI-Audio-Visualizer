#!/usr/bin/env bash
# ------------------------------------------------------------
# setup.sh – One-click environment setup for the Music project
# ------------------------------------------------------------
# Requirements:
#   • bash
#   • sudo privileges (for system packages)
# ------------------------------------------------------------

set -euo pipefail  

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

# ---------- 1.5. System update & essentials ----------
if command -v apt-get >/dev/null; then
    log "Updating system package lists..."
    sudo apt-get update -y || warn "System update failed — continuing anyway."

    log "Installing core build dependencies..."
    sudo apt-get install -y python3-dev python3-pip python3-venv build-essential || \
        error "Failed to install Python build dependencies."
else
    warn "apt-get not found — skipping system dependency install."
fi

# ---------- 2. Create virtual environment ----------
if [ -d "$VENV_NAME" ]; then
    log "Virtual environment '$VENV_NAME' already exists – reusing it."
else
    log "Creating virtual environment '$VENV_NAME' ..."
    python3 -m venv "$VENV_NAME" || error "Failed to create venv. Try reinstalling python3-venv."
fi

source "${VENV_NAME}/bin/activate" || error "Could not activate venv."

# ---------- 3. Upgrade pip ----------
log "Upgrading pip, setuptools, and wheel..."
pip install --upgrade pip setuptools wheel

# ---------- 4. Install Python packages ----------
log "Installing Python dependencies inside venv..."
pip install "${REQUIREMENTS[@]}"

# ---------- 5. Optional: system packages for GPIO ----------
if command -v apt-get >/dev/null; then
    if command -v sudo >/dev/null; then
        log "Installing optional system packages (lgpio/pigpio)..."
        sudo apt-get install -y python3-lgpio python3-pigpio pigpio || warn "Optional GPIO packages failed (non-critical)."
    else
        warn "'sudo' not found – skipping optional GPIO installs."
    fi
fi

# ---------- 6. Verify installation ----------
log "Verifying installed packages..."
for pkg in "${REQUIREMENTS[@]}"; do
    modname=$(echo "$pkg" | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    case "$modname" in
        pillow) modname="PIL" ;;
    esac
    python -c "import ${modname}; print('${pkg} OK')" 2>/dev/null || error "Failed to import $pkg"
done

# ---------- 7. Final instructions ----------
log "Setup complete!"
echo
echo "• Virtual env:       ${VENV_NAME}/"
echo "• Activate with:     source ${VENV_NAME}/bin/activate"
echo "• Start the app:     python music.py"
echo
echo "Tip: You can also run 'python3 start.py' to auto-activate and launch."

# Keep the terminal open if script was double-clicked
if [[ -t 1 ]]; then
    exec "${SHELL:-/bin/bash}"
fi
