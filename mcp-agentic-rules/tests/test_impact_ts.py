"""
Tests for TS/JS-aware impact analysis.
======================================
Guards relative-import resolution, pnpm-workspace package resolution, and
reverse-dependency lookups on a monorepo layout.
"""

from pathlib import Path
import json

import pytest

from scripts.impact import (
    DependencyGraph,
    parse_workspace_packages,
    resolve_js_import,
)


@pytest.fixture
def monorepo(tmp_path):
    root = tmp_path / "repo"
    (root / "apps" / "web" / "src").mkdir(parents=True)
    (root / "packages" / "ui" / "src").mkdir(parents=True)

    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'packages/*'\n")
    (root / "package.json").write_text(json.dumps({"name": "repo", "private": True}))

    (root / "packages" / "ui" / "package.json").write_text(
        json.dumps({"name": "@acme/ui", "main": "src/index.ts"}))
    (root / "packages" / "ui" / "src" / "index.ts").write_text(
        "export { Button } from './button';\n")
    (root / "packages" / "ui" / "src" / "button.ts").write_text(
        "export function Button(): string { return 'btn'; }\n")

    (root / "apps" / "web" / "src" / "helper.ts").write_text(
        "export const fmt = (s: string) => s.trim();\n")
    (root / "apps" / "web" / "src" / "page.tsx").write_text(
        "import { Button } from '@acme/ui';\n"
        "import { fmt } from './helper';\n"
        "export default function Page() { return Button() + fmt(' x '); }\n")

    (root / "node_modules" / "react").mkdir(parents=True)
    (root / "node_modules" / "react" / "index.js").write_text("module.exports = {};\n")
    yield root


class TestWorkspaceParsing:
    def test_maps_package_names_to_dirs(self, monorepo):
        mapping = parse_workspace_packages(monorepo)
        if "@acme/ui" not in mapping:
            raise AssertionError("workspace package not discovered: %r" % mapping)


class TestImportResolution:
    def test_relative_import_with_extension_fallback(self, monorepo):
        page = monorepo / "apps" / "web" / "src" / "page.tsx"
        resolved = resolve_js_import("./helper", page, monorepo, {})
        if resolved is None or "helper.ts" not in resolved:
            raise AssertionError("relative import not resolved: %r" % resolved)

    def test_workspace_package_resolves_to_entry(self, monorepo):
        page = monorepo / "apps" / "web" / "src" / "page.tsx"
        mapping = parse_workspace_packages(monorepo)
        resolved = resolve_js_import("@acme/ui", page, monorepo, mapping)
        if resolved is None or "index.ts" not in resolved:
            raise AssertionError("workspace import not resolved: %r" % resolved)

    def test_external_package_returns_none(self, monorepo):
        page = monorepo / "apps" / "web" / "src" / "page.tsx"
        if resolve_js_import("react", page, monorepo, {}) is not None:
            raise AssertionError("external packages must not resolve to repo files")


class TestGraph:
    def test_reverse_dependencies_across_workspace(self, monorepo):
        graph = DependencyGraph()
        graph.build(monorepo)

        page_key = str(Path("apps") / "web" / "src" / "page.tsx")
        helper_key = str(Path("apps") / "web" / "src" / "helper.ts")
        index_key = str(Path("packages") / "ui" / "src" / "index.ts")
        button_key = str(Path("packages") / "ui" / "src" / "button.ts")

        if page_key not in graph.get_dependents(helper_key):
            raise AssertionError("page.tsx must depend on helper.ts")
        if page_key not in graph.get_dependents(index_key):
            raise AssertionError("workspace import must register page.tsx as dependent")
        transitive = graph.get_transitive_dependents(button_key)
        if page_key not in transitive:
            raise AssertionError(
                "button.ts change must transitively impact page.tsx, got %r" % transitive)

    def test_node_modules_not_in_graph(self, monorepo):
        graph = DependencyGraph()
        graph.build(monorepo)
        for key in graph.all_files:
            if "node_modules" in key:
                raise AssertionError("node_modules leaked into the impact graph")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
