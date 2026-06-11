"""
Tests for the commands salvaged from the legacy nested tree.
============================================================
heal, graph, predict-context, hybrid-search, learn-patterns, and
hook-guardian were documented for months but lived only in an orphaned
duplicate of the package. These tests pin that they are registered,
importable, and agent-safe (no stdin hangs).
"""

from pathlib import Path
import importlib
import subprocess
import sys

import pytest

MCP_PY = Path(__file__).resolve().parent.parent / "mcp.py"

SALVAGED_MODULES = [
    "auto_heal", "call_graph", "correlation_tracker",
    "hook_guardian", "hybrid_graph", "predict_context", "py_skeleton",
]

SALVAGED_COMMANDS = [
    "heal", "graph", "call-graph", "correlate", "learn-patterns",
    "hook-guardian", "hybrid-search", "hybrid", "predict-context",
]


class TestSalvage:
    def test_modules_import(self):
        for mod in SALVAGED_MODULES:
            importlib.import_module("scripts." + mod)

    def test_commands_registered(self):
        source = MCP_PY.read_text(encoding="utf-8")
        for cmd in SALVAGED_COMMANDS:
            if "'%s'" % cmd not in source:
                raise AssertionError("command %r missing from mcp.py registry" % cmd)

    def test_heal_does_not_hang_on_silent_stdin(self):
        # Agents invoke tools with an open, silent stdin pipe; heal with no
        # args must fail fast instead of blocking on stdin.read() forever.
        result = subprocess.run(
            [sys.executable, str(MCP_PY), "heal"],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.PIPE)
        if result.returncode != 1:
            raise AssertionError(
                "heal with no args and non-tty stdin must exit 1, got %d"
                % result.returncode)

    def test_heal_analyzes_error_text(self):
        result = subprocess.run(
            [sys.executable, str(MCP_PY), "heal",
             "ModuleNotFoundError: No module named requests"],
            capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise AssertionError("heal with error text must succeed")

    def test_predict_context_runs(self):
        result = subprocess.run(
            [sys.executable, str(MCP_PY), "predict-context", "improve search"],
            capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise AssertionError(
                "predict-context failed: %s" % (result.stdout + result.stderr)[:300])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
