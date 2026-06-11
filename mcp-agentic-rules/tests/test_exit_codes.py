"""
Tests for the CLI exit-code contract.
=====================================
Contract: 0 = success, 1 = failure. Verified end-to-end through mcp.py in a
subprocess so re-exec and normalization paths are exercised for real.
"""

from pathlib import Path
import os
import subprocess
import sys

import pytest

MCP_PY = Path(__file__).resolve().parent.parent / "mcp.py"


def run_mcp(*args):
    env = dict(os.environ)
    env.pop("MCP_COMMAND", None)
    return subprocess.run(
        [sys.executable, str(MCP_PY), *args],
        capture_output=True, text=True, timeout=120, env=env)


class TestExitCodes:
    def test_help_exits_zero(self):
        result = run_mcp("help")
        if result.returncode != 0:
            raise AssertionError("help must exit 0, got %d" % result.returncode)

    def test_unknown_command_exits_one(self):
        result = run_mcp("definitely-not-a-command")
        if result.returncode != 1:
            raise AssertionError(
                "unknown command must exit 1, got %d" % result.returncode)

    def test_todos_exits_zero(self):
        result = run_mcp("todos")
        if result.returncode != 0:
            raise AssertionError(
                "todos must exit 0, got %d; stderr: %s"
                % (result.returncode, result.stderr[:300]))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
