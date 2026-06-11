"""
Tests for scalable, language-agnostic source-file discovery.
============================================================
Covers find_source_files (the large-codebase walker) and the
backwards-compatible find_python_files wrapper.
"""

from pathlib import Path
import tempfile

import pytest


@pytest.fixture
def mixed_project():
    """A project tree that mixes languages, build output, and vendored deps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Real source in a few languages.
        (root / "apps" / "web" / "src").mkdir(parents=True)
        (root / "apps" / "web" / "src" / "App.tsx").write_text("export const App = () => null;\n")
        (root / "apps" / "web" / "src" / "util.ts").write_text("export function add(a: number, b: number) { return a + b; }\n")
        (root / "packages" / "core").mkdir(parents=True)
        (root / "packages" / "core" / "index.js").write_text("module.exports = {};\n")
        (root / "service.py").write_text("def handler():\n    return 1\n")

        # Things that must be pruned / skipped.
        (root / "node_modules" / "left-pad").mkdir(parents=True)
        (root / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1;\n")
        (root / ".git").mkdir()
        (root / ".git" / "hooks.js").write_text("// not real source\n")
        (root / "dist").mkdir()
        (root / "dist" / "bundle.ts").write_text("// built output\n")
        (root / "apps" / "web" / "src" / "vendor.min.js").write_text("var a=1;\n")

        yield root


class TestFindSourceFiles:
    """Tests for find_source_files."""

    def _names(self, root):
        from scripts.utils import find_source_files
        return {p.name for p in find_source_files(root)}

    def test_finds_typescript_and_javascript(self, mixed_project):
        names = self._names(mixed_project)
        for expected in ("App.tsx", "util.ts", "index.js", "service.py"):
            if expected not in names:
                raise AssertionError(f"Should have found {expected}; got {sorted(names)}")

    def test_prunes_node_modules_and_git_and_dist(self, mixed_project):
        from scripts.utils import find_source_files
        paths = list(find_source_files(mixed_project))
        for p in paths:
            parts = p.parts
            if "node_modules" in parts:
                raise AssertionError("Must never descend into node_modules")
            if ".git" in parts:
                raise AssertionError("Must never descend into .git")
            if "dist" in parts:
                raise AssertionError("Must never descend into dist")

    def test_skips_minified(self, mixed_project):
        names = self._names(mixed_project)
        if "vendor.min.js" in names:
            raise AssertionError("Minified bundles should be skipped")

    def test_respects_size_cap(self, mixed_project):
        from scripts.utils import find_source_files
        big = mixed_project / "packages" / "core" / "huge.ts"
        big.write_text("// x\n" + ("a" * 5000))
        small = list(find_source_files(mixed_project, max_file_bytes=1000))
        if any(p.name == "huge.ts" for p in small):
            raise AssertionError("Files above the size cap should be skipped")
        # With a generous cap it should reappear.
        large = list(find_source_files(mixed_project, max_file_bytes=10_000_000))
        if not any(p.name == "huge.ts" for p in large):
            raise AssertionError("File should be found when under the size cap")

    def test_extension_filter(self, mixed_project):
        from scripts.utils import find_source_files
        only_ts = list(find_source_files(mixed_project, extensions={'.ts', '.tsx'}))
        suffixes = {p.suffix for p in only_ts}
        if suffixes - {'.ts', '.tsx'}:
            raise AssertionError(f"Extension filter leaked: {suffixes}")

    def test_max_files_cap(self, mixed_project):
        from scripts.utils import find_source_files
        capped = list(find_source_files(mixed_project, max_files=2))
        if len(capped) != 2:
            raise AssertionError(f"max_files cap not honoured: got {len(capped)}")

    def test_gitignore_dirs_pruned(self, mixed_project):
        from scripts.utils import find_source_files
        (mixed_project / ".gitignore").write_text("generated/\n# comment\n*.log\n")
        (mixed_project / "generated").mkdir()
        (mixed_project / "generated" / "schema.ts").write_text("export type X = 1;\n")
        names = {p.name for p in find_source_files(mixed_project)}
        if "schema.ts" in names:
            raise AssertionError("Directory ignored by .gitignore should be pruned")


class TestFindPythonFilesCompat:
    """The legacy wrapper must keep working for existing callers."""

    def test_finds_only_python(self, mixed_project):
        from scripts.utils import find_python_files
        paths = list(find_python_files(mixed_project))
        if not paths:
            raise AssertionError("Should find the Python file")
        if any(p.suffix not in ('.py', '.pyi') for p in paths):
            raise AssertionError("find_python_files must yield only Python files")
        if not any(p.name == "service.py" for p in paths):
            raise AssertionError("Should have found service.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
