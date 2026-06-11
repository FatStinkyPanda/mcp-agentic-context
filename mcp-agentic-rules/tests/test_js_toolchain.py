"""
Tests for the JS/TS toolchain bridge.
=====================================
Pure-parser and detection tests; no node required.
"""

from pathlib import Path
import json

import pytest

from scripts.js_toolchain import (
    detect_js_project,
    parse_eslint_json,
    parse_tsc_output,
    parse_pnpm_audit_json,
    runner_prefix,
)


class TestDetection:
    def test_non_js_project(self, tmp_path):
        if detect_js_project(tmp_path) != {}:
            raise AssertionError("dir without package.json must not detect as JS")

    def test_pnpm_monorepo_with_tools(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "devDependencies": {"eslint": "^9.0.0", "typescript": "^5.4.0"},
            "scripts": {"lint": "eslint ."}}))
        (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n")
        info = detect_js_project(tmp_path)
        for key in ("js_project", "eslint", "typescript", "pnpm"):
            if not info.get(key):
                raise AssertionError("expected %s=True, got %r" % (key, info))
        if runner_prefix(tmp_path) != ["pnpm", "exec"]:
            raise AssertionError("pnpm projects must run tools via pnpm exec")


class TestEslintParser:
    CANNED = json.dumps([
        {"filePath": "C:/repo/apps/web/src/page.tsx", "messages": [
            {"line": 12, "severity": 2, "ruleId": "no-unused-vars",
             "message": "'x' is defined but never used."},
            {"line": 30, "severity": 1, "ruleId": "eqeqeq",
             "message": "Expected '===' and instead saw '=='."},
        ]},
        {"filePath": "C:/repo/packages/ui/button.tsx", "messages": []},
    ])

    def test_parses_messages(self):
        findings = parse_eslint_json(self.CANNED)
        if len(findings) != 2:
            raise AssertionError("expected 2 findings, got %d" % len(findings))
        if findings[0]["severity"] != "error" or findings[1]["severity"] != "warning":
            raise AssertionError("severity mapping broken: %r" % findings)
        if findings[0]["rule"] != "no-unused-vars":
            raise AssertionError("ruleId lost in parsing")

    def test_tolerates_banner_noise(self):
        noisy = "> repo@1.0.0 lint\n> eslint . --format json\n\n" + self.CANNED
        if len(parse_eslint_json(noisy)) != 2:
            raise AssertionError("parser must skip runner banner before the JSON")

    def test_garbage_returns_empty(self):
        if parse_eslint_json("not json at all") != []:
            raise AssertionError("garbage input must yield no findings")


class TestTscParser:
    CANNED = (
        "apps/web/src/page.tsx(14,7): error TS2322: Type 'string' is not "
        "assignable to type 'number'.\n"
        "packages/ui/button.tsx(3,1): warning TS6133: 'React' is declared "
        "but its value is never read.\n"
        "some unrelated line\n")

    def test_parses_diagnostics(self):
        findings = parse_tsc_output(self.CANNED)
        if len(findings) != 2:
            raise AssertionError("expected 2 diagnostics, got %d" % len(findings))
        first = findings[0]
        if first["rule"] != "TS2322" or first["line"] != 14 or first["severity"] != "error":
            raise AssertionError("tsc diagnostic parsed wrong: %r" % first)


class TestAuditParser:
    def test_parses_advisories(self):
        canned = json.dumps({"advisories": {
            "1": {"severity": "high", "title": "Prototype Pollution",
                  "module_name": "lodash", "url": "https://example.test/1"}}})
        findings = parse_pnpm_audit_json(canned)
        if len(findings) != 1 or findings[0]["module"] != "lodash":
            raise AssertionError("audit advisory parsed wrong: %r" % findings)

    def test_empty_or_garbage(self):
        if parse_pnpm_audit_json("") != [] or parse_pnpm_audit_json("nope") != []:
            raise AssertionError("non-JSON audit output must yield no findings")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
