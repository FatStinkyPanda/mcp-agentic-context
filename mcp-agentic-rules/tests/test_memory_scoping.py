"""
Tests for project-scoped memory.
================================
The user-level store is shared across every project; recall must not leak
other projects' memories by default, while legacy/global rows stay visible.
Uses an isolated store path so the real ~/.mcp is never touched.
"""

from pathlib import Path
import os

import pytest

from scripts.memory import Memory, MemoryStore, current_project_id


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(storage_path=tmp_path / "memstore")
    yield s
    if s.conn:
        s.conn.close()


@pytest.fixture
def in_project(tmp_path, monkeypatch):
    root = tmp_path / "proj-a"
    root.mkdir()
    (root / "package.json").write_text("{}")
    monkeypatch.delenv("MCP_ROOT", raising=False)
    old = os.getcwd()
    os.chdir(root)
    try:
        yield root
    finally:
        os.chdir(old)


class TestScoping:
    def test_remember_stamps_current_project(self, store, in_project):
        mem = store.remember("scoped-key", "scoped value")
        expected = current_project_id()
        if not expected:
            raise AssertionError("test project must resolve to a project id")
        if mem.project != expected:
            raise AssertionError(
                "remember must stamp the current project, got %r" % mem.project)

    def test_recall_filters_other_projects(self, store, in_project):
        store.remember("mine", "memory from this project")
        store.remember("theirs", "memory from another project",
                       project="other-project-deadbeef")
        store.remember("shared", "global memory", project="")

        keys = {m.key for m in store.recall("memory")}
        if "theirs" in keys:
            raise AssertionError("recall leaked another project's memory")
        if "mine" not in keys:
            raise AssertionError("recall must return this project's memory")
        if "shared" not in keys:
            raise AssertionError("recall must include global memories")

    def test_recall_all_projects_flag(self, store, in_project):
        store.remember("theirs", "memory from another project",
                       project="other-project-deadbeef")
        keys = {m.key for m in store.recall("memory", all_projects=True)}
        if "theirs" not in keys:
            raise AssertionError("all_projects=True must search the whole store")

    def test_save_preserves_other_projects_rows(self, store, in_project):
        # recall() persists access counts via save(); that must never drop
        # rows belonging to other projects.
        store.remember("theirs", "memory from another project",
                       project="other-project-deadbeef")
        store.recall("memory")  # triggers save()
        survivor = store.get_by_key("theirs")
        if survivor is None:
            raise AssertionError("save() after scoped recall dropped another project's row")

    def test_legacy_rows_default_to_global(self, store, in_project):
        # Simulate a pre-scoping row written without a project value.
        with store.conn:
            store.conn.execute(
                "INSERT INTO memories (key, value, tags, created, updated, access_count, embedding, project) "
                "VALUES ('legacy', 'old memory', '', '', '', 0, '[]', '')")
        keys = {m.key for m in store.recall("old memory")}
        if "legacy" not in keys:
            raise AssertionError("legacy unscoped rows must stay visible everywhere")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
