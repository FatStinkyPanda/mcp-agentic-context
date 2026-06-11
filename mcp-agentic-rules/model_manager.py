#!/usr/bin/env python3
"""
Antigravity Model Priority Manager
Manages model selection based on user preference and availability.
Priority 1: Gemini 3 Flash
Priority 2: Claude Opus (Latest/4.5 Thinking)
"""

from pathlib import Path
import json
import os
import sys

# Configuration path: override with MCP_MODEL_PREFS; defaults to the per-user
# MCP data directory so no machine-specific path is baked into the source.
def _config_path() -> Path:
    override = os.environ.get("MCP_MODEL_PREFS")
    if override:
        return Path(override)
    return Path.home() / ".mcp" / "model_preferences.json"


CONFIG_PATH = _config_path()

DEFAULT_PRIORITY = [
    "Gemini 3 Flash",
    "Claude Opus (4.5 Thinking)",
    "GPT-4o"
]

def get_preferences():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {"priority": DEFAULT_PRIORITY, "current": DEFAULT_PRIORITY[0]}

def save_preferences(prefs):
    with open(CONFIG_PATH, "w") as f:
        json.dump(prefs, f, indent=2)

def get_current_model():
    prefs = get_preferences()
    return prefs.get("current", DEFAULT_PRIORITY[0])

def switch_model(reason="manual"):
    prefs = get_preferences()
    priority = prefs.get("priority", DEFAULT_PRIORITY)
    current = prefs.get("current", priority[0])

    try:
        idx = priority.index(current)
        next_idx = (idx + 1) % len(priority)
        prefs["current"] = priority[next_idx]
        save_preferences(prefs)
        print(f"[MODEL] Switched to {prefs['current']} (Reason: {reason})")
        return prefs["current"]
    except ValueError:
        prefs["current"] = priority[0]
        save_preferences(prefs)
        return priority[0]

def main():
    if len(sys.argv) < 2:
        print(get_current_model())
        return 0

    cmd = sys.argv[1]
    if cmd == "status":
        print(f"Current Priority Model: {get_current_model()}")
    elif cmd == "switch":
        reason = sys.argv[2] if len(sys.argv) > 2 else "limit reached"
        switch_model(reason)
    elif cmd == "reset":
        prefs = {"priority": DEFAULT_PRIORITY, "current": DEFAULT_PRIORITY[0]}
        save_preferences(prefs)
        print("[MODEL] Preferences reset to defaults.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
