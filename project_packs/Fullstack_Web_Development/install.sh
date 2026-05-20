#!/usr/bin/env bash
# Usage: ./install.sh
# Bootstraps Python + Web Development dependencies on Unix systems.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
WHEELS_DIR="$SCRIPT_DIR/wheels"

# Step 1: Detect Python
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python not found. Please install Python 3.8+."
    exit 1
fi

# Step 2: Create a venv
VENV_PATH="$(pwd)/.venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating .venv..."
    $PYTHON_CMD -m venv "$VENV_PATH"
fi

# Step 3: Activate and install dependencies
echo "Activating venv and installing Web Development dependencies..."
source "$VENV_PATH/bin/activate"

# Upgrade pip
python -m pip install --upgrade pip

if [ -d "$WHEELS_DIR" ]; then
    echo "Installing from local wheels..."
    pip install --no-index --find-links "$WHEELS_DIR" -r "$REQ_FILE"
else
    echo "Local wheels not found. Installing from online PyPI..."
    pip install -r "$REQ_FILE"
fi

echo "Setup complete! Venv is active."
