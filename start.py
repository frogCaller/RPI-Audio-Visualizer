import os
import subprocess
import sys
from pathlib import Path

# --- Configuration ---
VENV_DIR = Path(__file__).parent / "Music_env"
PYTHON_EXE = VENV_DIR / "bin" / "python"
TARGET_SCRIPT = Path(__file__).parent / "music.py"

# --- Safety checks ---
if not VENV_DIR.exists():
    sys.exit("[ERROR] Virtual environment not found. Run setup.sh first.")

if not TARGET_SCRIPT.exists():
    sys.exit("[ERROR] music.py not found in current directory.")

# --- Activate and run ---
print(f"[INFO] Activating environment: {VENV_DIR}")
print(f"[INFO] Running script: {TARGET_SCRIPT}\n")

# Run the target script using the venv's Python
try:
    subprocess.run([str(PYTHON_EXE), str(TARGET_SCRIPT)], check=True)
except subprocess.CalledProcessError as e:
    print(f"[ERROR] music.py exited with code {e.returncode}")
except FileNotFoundError:
    sys.exit("[ERROR] Could not find python executable in virtual environment.")
