"""
Tests for the mcp.py -> module dispatch contract.
=================================================
mcp.py strips the verb from argv and exposes it via MCP_COMMAND. Multi-verb
modules (index/search -> vector_store, remember/recall/forget -> memory)
must resolve the verb from MCP_COMMAND, otherwise "mcp.py search q" silently
does nothing and "mcp.py forget key" recalls instead of deleting.
"""

from pathlib import Path
import os
import sys
import tempfile

import pytest


@pytest.fixture
def ts_project():
    # chdir is restored BEFORE TemporaryDirectory cleanup; Windows cannot
    # delete a directory that is still the process working directory.
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".mcp").mkdir()
        (root / "src").mkdir()
        (root / "src" / "settings.ts").write_text(
            "export function loadUserSettings(id: string): object {\n"
            "  return { id: id, theme: 'dark' };\n"
            "}\n")
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(old_cwd)


class TestVectorStoreDispatch:
    def test_search_verb_resolved_from_env(self, ts_project, monkeypatch, capsys):
        from scripts import vector_store
        # Build a tiny index first via the documented API.
        store = vector_store.VectorStore()
        store.index_codebase(ts_project)
        store.save()
        # Simulate mcp.py dispatch of: mcp.py search "load user settings"
        monkeypatch.setenv("MCP_COMMAND", "search")
        monkeypatch.setattr(sys, "argv", ["scripts/vector_store.py", "load", "user", "settings"])
        rc = vector_store.main()
        out = capsys.readouterr().out
        if rc not in (0, None):
            raise AssertionError("search via MCP_COMMAND must succeed, got rc=%r" % rc)
        if "Searching:" not in out:
            raise AssertionError("search verb was not resolved from MCP_COMMAND; output: %s" % out[:300])
        if "settings.ts" not in out:
            raise AssertionError("search must return the indexed TS function; output: %s" % out[:300])

    def test_direct_invocation_still_accepts_verb_in_argv(self, ts_project, monkeypatch, capsys):
        from scripts import vector_store
        store = vector_store.VectorStore()
        store.index_codebase(ts_project)
        store.save()
        monkeypatch.delenv("MCP_COMMAND", raising=False)
        monkeypatch.setattr(sys, "argv", ["vector_store.py", "search", "load", "user", "settings"])
        rc = vector_store.main()
        out = capsys.readouterr().out
        if rc not in (0, None) or "settings.ts" not in out:
            raise AssertionError("direct 'vector_store.py search ...' invocation regressed")

    def test_unknown_verb_prints_usage(self, ts_project, monkeypatch, capsys):
        from scripts import vector_store
        monkeypatch.delenv("MCP_COMMAND", raising=False)
        monkeypatch.setattr(sys, "argv", ["vector_store.py", "bogus"])
        rc = vector_store.main()
        out = capsys.readouterr().out
        if rc != 1 or "Usage:" not in out:
            raise AssertionError("unknown verb must print usage and return 1")


class TestMemoryForgetDispatch:
    def test_forget_verb_deletes_instead_of_recalling(self, ts_project, monkeypatch, capsys):
        from scripts import memory
        store = memory.get_store()
        store.remember("dispatch-test-key", "dispatch test value")
        try:
            monkeypatch.setenv("MCP_COMMAND", "forget")
            monkeypatch.setattr(sys, "argv", ["scripts/memory.py", "dispatch-test-key"])
            memory.main()
            out = capsys.readouterr().out
            if "Forgot: dispatch-test-key" not in out:
                raise AssertionError("forget verb must delete the memory; output: %s" % out[:300])
        finally:
            store.forget("dispatch-test-key")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
