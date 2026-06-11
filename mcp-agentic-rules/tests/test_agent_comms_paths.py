"""
Tests for agent_comms path configuration.
=========================================
Guards that no machine-specific path is baked into the source and that
MCP_NSYNC_PATH overrides the default per-user location.
"""

from pathlib import Path

import pytest

from scripts import agent_comms


class TestNsyncPath:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MCP_NSYNC_PATH", str(tmp_path / "shared"))
        if agent_comms.get_nsync_path() != tmp_path / "shared":
            raise AssertionError("MCP_NSYNC_PATH must override the default")

    def test_default_is_per_user(self, monkeypatch):
        monkeypatch.delenv("MCP_NSYNC_PATH", raising=False)
        default = agent_comms.get_nsync_path()
        if Path.home() not in default.parents:
            raise AssertionError("default NSync path must live under the user home")

    def test_no_personal_paths_in_source(self):
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "agent_comms.py").read_text()
        for needle in ("dbiss", "p4nd4pr0t0c01", "_BLANK_"):
            if needle in source:
                raise AssertionError("personal path %r is still in agent_comms.py" % needle)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
