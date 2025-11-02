#!/usr/bin/env bash
# ------------------------------------------------------------
# setup.sh – One-click environment setup for the Music project
# ------------------------------------------------------------

set -euo pipefail

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

# ---- Color helpers ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- Ensure apt and sudo available ----
if ! command -v apt-get >/dev/null; then
    error "This script currently supports apt-based systems (Ubuntu/Debian)."
fi

# ---- Basic tools check ----
log "Checking required system tools..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip build-essential

# ---- Create venv ----
if [ ! -d "$VENV_NAME" ]; then
    log "Creating virtual environment: $VENV_NAME"
    python3 -m venv "$VENV_NAME"
else
    log "Reusing existing venv: $VENV_NAME"
fi

source "$VENV_NAME/bin/activate"

# ---- Upgrade pip ----
log "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# ---- Install Python deps ----
log "Installing project dependencies..."
pip install "${REQUIREMENTS[@]}" || warn "Some Python modules failed; continuing."

# ---- Try installing GPIO support only if on a Pi ----
if grep -qi "raspberry" /proc/cpuinfo 2>/dev/null; then
    log "Detected Raspberry Pi — installing GPIO tools..."
    sudo apt-get install -y python3-lgpio python3-pigpio pigpio
else
    warn "Not a Raspberry Pi — skipping GPIO system packages."
fi

# ---- Verify installs ----
log "Verifying Python imports..."
for pkg in "${REQUIREMENTS[@]}"; do
    mod=$(echo "$pkg" | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    [ "$mod" = "pillow" ] && mod="PIL"
    python -c "import ${mod}" 2>/dev/null && echo "✓ $pkg" || warn "⚠️  $pkg failed to import"
done

log "Setup complete!"
echo
echo "• Virtual env. created:                  ${VENV_NAME}/"
echo "• To activate it:     source ${VENV_NAME}/bin/activate"
echo "• To start the app:                 python music.py"
echo
echo "💡 Tip: You can run 'python start.py' — it will automatically"
echo "        activate the environment and launch music.py for you."
