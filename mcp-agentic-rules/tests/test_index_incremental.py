"""
Tests for incremental change detection in index_all.
=====================================================
Guards that incremental scans prune ignored directories and honour mtime.
"""

from pathlib import Path
import os
import tempfile

import pytest


@pytest.fixture
def project():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("export const a = 1;\n")
        (root / "README.md").write_text("# docs\n")
        (root / "node_modules" / "dep").mkdir(parents=True)
        (root / "node_modules" / "dep" / "b.ts").write_text("export const b = 2;\n")
        yield root


class TestGetChangedFiles:
    def test_detects_recent_changes_and_prunes_deps(self, project):
        from scripts.index_all import get_changed_files
        # Baseline of 0 => everything counts as changed.
        changed = get_changed_files(project, 0.0)
        names = {p.name for p in changed}
        if "a.ts" not in names:
            raise AssertionError("Should detect the changed TS source file")
        if "README.md" not in names:
            raise AssertionError("Should detect changed docs for the doc index")
        for p in changed:
            if "node_modules" in p.parts:
                raise AssertionError("Incremental scan must not descend into node_modules")

    def test_respects_mtime_baseline(self, project):
        from scripts.index_all import get_changed_files
        old = project / "src" / "a.ts"
        # Push the file's mtime well into the past.
        os.utime(old, (1000, 1000))
        changed = get_changed_files(project, 5000.0)
        if any(p.name == "a.ts" for p in changed):
            raise AssertionError("Files older than the baseline must be skipped")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
