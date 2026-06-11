"""
Tests for single-file review/security and autocontext formatting fixes.
=======================================================================
review/security with a single-file path previously scanned 0 files and
reported PASSED; autocontext labeled every excerpt as python.
"""

from pathlib import Path

import pytest

from scripts.autocontext import _fence_lang
from scripts.review import review_project, js_toolchain_issues
from scripts.security import security_audit


@pytest.fixture
def py_file(tmp_path):
    target = tmp_path / "logic.py"
    target.write_text(
        "def visible_function(x):\n"
        "    return eval(x)\n")
    yield target


class TestSingleFileReview:
    def test_python_file_is_actually_reviewed(self, py_file):
        report = review_project(py_file)
        if report.files_reviewed != 1:
            raise AssertionError(
                "single .py file must be reviewed, got files_reviewed=%d"
                % report.files_reviewed)

    def test_python_file_is_actually_audited(self, py_file):
        report = security_audit(py_file)
        if report.files_scanned != 1:
            raise AssertionError(
                "single .py file must be scanned, got files_scanned=%d"
                % report.files_scanned)
        if not any("eval" in (i.title + i.description).lower()
                   for i in report.issues):
            raise AssertionError("eval() in the file must be flagged")

    def test_js_file_resolves_owning_project(self, tmp_path, monkeypatch):
        import json
        from scripts import review as review_mod
        (tmp_path / "package.json").write_text(json.dumps(
            {"devDependencies": {"eslint": "^9.0.0"}}))
        (tmp_path / "src").mkdir()
        target = tmp_path / "src" / "widget.ts"
        target.write_text("export const w = 1;\n")

        captured = {}

        def fake_run_eslint(root, timeout=0, target=None):
            captured["root"] = Path(root)
            captured["target"] = target
            return []

        import scripts.js_toolchain as jt
        monkeypatch.setattr(jt, "run_eslint", fake_run_eslint)
        js_toolchain_issues(target)
        if captured.get("root") != tmp_path:
            raise AssertionError(
                "single-file JS review must resolve the owning project, "
                "got %r" % captured.get("root"))
        if captured.get("target") != target:
            raise AssertionError("eslint must target just the given file")

    def test_non_source_file_reports_zero_not_crash(self, tmp_path):
        target = tmp_path / "notes.txt"
        target.write_text("hello\n")
        report = review_project(target)
        if report.files_reviewed != 0:
            raise AssertionError("non-source file reviews nothing")


class TestFenceLang:
    def test_known_extensions(self):
        cases = {
            "a.py": "python", "b.ts": "typescript", "c.tsx": "tsx",
            "d.jsx": "jsx", "e.js": "javascript", "f.json": "json",
        }
        for name, expected in cases.items():
            got = _fence_lang(Path(name))
            if got != expected:
                raise AssertionError("%s -> %s, expected %s" % (name, got, expected))

    def test_unknown_extension_is_text(self):
        if _fence_lang(Path("weird.xyz")) != "text":
            raise AssertionError("unknown extensions must use a neutral fence")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
