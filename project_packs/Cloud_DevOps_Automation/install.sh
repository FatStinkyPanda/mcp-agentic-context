#!/bin/bash
# Auto-generated installer for Cloud_DevOps_Automation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
WHEELS_DIR="$SCRIPT_DIR/wheels"
VENV_PATH="./.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating .venv..."
    python3 -m venv "$VENV_PATH"
fi

echo "Activating .venv..."
source "$VENV_PATH/bin/activate"
python3 -m pip install --upgrade pip

if [ -d "$WHEELS_DIR" ]; then
    pip install --no-index --find-links "$WHEELS_DIR" -r "$REQ_FILE"
else
    pip install -r "$REQ_FILE"
fi
echo "Setup complete!"
