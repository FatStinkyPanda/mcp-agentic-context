#!/usr/bin/env bash
# Usage: ./install.sh
# Bootstraps Python + ML dependencies on Unix systems.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
WHEELS_DIR="$SCRIPT_DIR/cu121-py312"

# Step 1: Detect Python
PYTHON_CMD=""
if command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python not found. Please install Python 3.12."
    exit 1
fi

# Step 2: Create a venv
VENV_PATH="$(pwd)/.venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating .venv..."
    $PYTHON_CMD -m venv "$VENV_PATH"
fi

# Step 3: Activate and install dependencies
echo "Activating venv and installing ML dependencies..."
source "$VENV_PATH/bin/activate"

# Upgrade pip
python -m pip install --upgrade pip

if [ -d "$WHEELS_DIR" ]; then
    echo "Attempting to install from local wheels..."
    if pip install --no-index --find-links "$WHEELS_DIR" -r "$REQ_FILE"; then
        echo "Successfully installed from local wheels."
    else
        echo "Local wheels install failed (likely platform mismatch). Falling back to online PyPI..."
        pip install -r "$REQ_FILE"
    fi
else
    echo "Local wheels not found. Installing from online PyPI..."
    pip install -r "$REQ_FILE"
fi

echo "Setup complete! Venv is active."
