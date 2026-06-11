"""
Tests for the skeleton and state commands.
==========================================
Both were documented for a long time but missing from the build; these
tests pin the actual behavior now that they exist.
"""

from pathlib import Path
import json
import sys

import pytest

from scripts.skeleton import skeleton, skeleton_for_file
from scripts import project_state


@pytest.fixture
def ts_tree(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "loader.ts").write_text(
        "import { thing } from './thing';\n\n"
        "export function loadSettings(id: string): object {\n"
        "  return { id: id };\n"
        "}\n\n"
        "export function saveSettings(s: object): void {\n"
        "}\n")
    (root / "src" / "util.py").write_text(
        "def helper(x):\n    \"\"\"Add one.\"\"\"\n    return x + 1\n")
    (root / "node_modules" / "junk").mkdir(parents=True)
    (root / "node_modules" / "junk" / "dep.ts").write_text("export const j = 1;\n")
    yield root


class TestSkeleton:
    def test_file_skeleton_lists_ts_signatures(self, ts_tree):
        out = skeleton_for_file(ts_tree / "src" / "loader.ts")
        if "loadSettings" not in out or "saveSettings" not in out:
            raise AssertionError("TS function names missing from skeleton: %s" % out)
        if "return { id: id }" in out:
            raise AssertionError("skeleton must not include function bodies")

    def test_directory_skeleton_prunes_node_modules(self, ts_tree):
        out = skeleton(ts_tree)
        if "loader.ts" not in out:
            raise AssertionError("directory skeleton missing source files")
        if "node_modules" in out:
            raise AssertionError("directory skeleton must prune node_modules")

    def test_budget_truncation(self, ts_tree):
        for i in range(60):
            (ts_tree / "src" / ("gen%02d.py" % i)).write_text(
                "def generated_%02d():\n    return %d\n" % (i, i))
        out = skeleton(ts_tree, budget_chars=1500)
        if len(out) > 4000:
            raise AssertionError("budget did not cap skeleton output")
        if "[TRUNCATED]" not in out:
            raise AssertionError("truncated skeleton must carry a notice")


class TestState:
    def test_round_trip(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "proj"
        (root / ".mcp").mkdir(parents=True)
        monkeypatch.setattr(project_state, "find_project_root", lambda: root)

        monkeypatch.setattr(sys, "argv", ["project_state.py", "--set-goal", "Ship the filter bar"])
        project_state.main()
        monkeypatch.setattr(sys, "argv", ["project_state.py", "--add-task", "Add unit tests"])
        project_state.main()
        monkeypatch.setattr(sys, "argv", ["project_state.py", "--done", "1"])
        rc = project_state.main()
        out = capsys.readouterr().out
        if rc not in (0, None):
            raise AssertionError("state commands must succeed")
        if "Ship the filter bar" not in out:
            raise AssertionError("goal missing from state view")
        if "[x] 1. Add unit tests" not in out:
            raise AssertionError("completed task not rendered as done")

        data = json.loads((root / ".mcp" / "project_state.json").read_text())
        if data["goal"] != "Ship the filter bar" or not data["tasks"][0]["done"]:
            raise AssertionError("state not persisted correctly")

    def test_done_out_of_range_fails(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        (root / ".mcp").mkdir(parents=True)
        monkeypatch.setattr(project_state, "find_project_root", lambda: root)
        monkeypatch.setattr(sys, "argv", ["project_state.py", "--done", "7"])
        if project_state.main() != 1:
            raise AssertionError("marking a nonexistent task done must fail with 1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
