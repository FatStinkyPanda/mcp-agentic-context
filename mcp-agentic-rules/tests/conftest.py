"""
Shared fixtures: every collab-touching test runs against an ISOLATED store.
get_nsync_path() reads MCP_NSYNC_PATH at call time (pinned by a test below),
so pointing it at tmp_path isolates leases/claims/journal/presence/mail
without touching the developer's real ~/.mcp store.
"""

import os

import pytest


@pytest.fixture
def collab_store(monkeypatch, tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("MCP_NSYNC_PATH", str(store))
    monkeypatch.setenv("AGENT_IDENTITY", "pytest-%d" % os.getpid())
    monkeypatch.setenv("MCP_NSYNC_AUTOSYNC", "0")
    monkeypatch.delenv("COLLAB_FAKE_GH", raising=False)
    return store
