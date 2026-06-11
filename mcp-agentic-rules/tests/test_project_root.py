"""
Tests for project root detection.
=================================
Guards that JS/TS monorepos are recognized, that the user home directory is
never chosen as a project root (the global ~/.mcp store matches the '.mcp'
marker), and that the install parent wins for markerless projects.
"""

from pathlib import Path
import os
import tempfile

import pytest

from scripts.utils import find_project_root


@pytest.fixture
def no_mcp_root_env(monkeypatch):
    monkeypatch.delenv("MCP_ROOT", raising=False)


class TestMarkers:
    def test_package_json_is_a_root_marker(self, no_mcp_root_env):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            (root / "package.json").write_text("{}")
            (root / "apps" / "web" / "src").mkdir(parents=True)
            found = find_project_root(start=root / "apps" / "web" / "src")
            if found != root:
                raise AssertionError("package.json must mark a JS project root, got %r" % found)

    def test_pnpm_workspace_is_a_root_marker(self, no_mcp_root_env):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n")
            (root / "packages" / "ui").mkdir(parents=True)
            found = find_project_root(start=root / "packages" / "ui")
            if found != root:
                raise AssertionError("pnpm-workspace.yaml must mark a monorepo root, got %r" % found)


class TestHomeIsNeverRoot:
    def test_home_directory_is_never_returned(self, no_mcp_root_env):
        # Even when started from a markerless dir directly under home (the
        # global ~/.mcp store exists on dev machines), home must not win.
        found = find_project_root(start=Path.home())
        if found is not None and Path(found).resolve() == Path.home().resolve():
            raise AssertionError("home directory must never be a project root")

    def test_markerless_project_with_install_resolves_to_install_parent(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            pkg = root / "mcp-agentic-rules"
            pkg.mkdir()
            monkeypatch.setenv("MCP_ROOT", str(pkg))
            found = find_project_root(start=root)
            if found != root:
                raise AssertionError(
                    "markerless project containing the install must resolve to the "
                    "install parent, got %r" % found)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
