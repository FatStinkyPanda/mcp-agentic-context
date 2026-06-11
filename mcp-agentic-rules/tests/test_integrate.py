"""
Tests for the integrate command (self-advertising install).
===========================================================
Guards idempotency (re-running never duplicates sections), preservation of
existing CLAUDE.md content, and non-destructive .mcp.json merging.
"""

from pathlib import Path
import json

import pytest

from scripts.integrate import (
    MARK_END,
    MARK_START,
    integrate,
    upsert_section,
    write_mcp_json,
)


class TestUpsertSection:
    def test_creates_missing_file(self, tmp_path):
        target = tmp_path / "CLAUDE.md"
        if upsert_section(target) != "created":
            raise AssertionError("missing file must be created")
        text = target.read_text(encoding="utf-8")
        if MARK_START not in text or "WHEN to reach for these tools" not in text:
            raise AssertionError("created file missing the section content")

    def test_appends_preserving_existing_content(self, tmp_path):
        target = tmp_path / "CLAUDE.md"
        target.write_text("# My project rules\n\nUse tabs, never spaces.\n",
                          encoding="utf-8")
        if upsert_section(target) != "appended":
            raise AssertionError("existing file without markers must be appended to")
        text = target.read_text(encoding="utf-8")
        if "Use tabs, never spaces." not in text:
            raise AssertionError("existing content was clobbered")
        if text.index("Use tabs") > text.index(MARK_START):
            raise AssertionError("section must be appended after existing content")

    def test_rerun_replaces_in_place(self, tmp_path):
        target = tmp_path / "CLAUDE.md"
        target.write_text("# Rules\n", encoding="utf-8")
        upsert_section(target)
        upsert_section(target)
        upsert_section(target)
        text = target.read_text(encoding="utf-8")
        if text.count(MARK_START) != 1 or text.count(MARK_END) != 1:
            raise AssertionError("re-running integrate must not duplicate sections")


class TestMcpJson:
    def test_creates_registration(self, tmp_path):
        if write_mcp_json(tmp_path) != "created":
            raise AssertionError("missing .mcp.json must be created")
        data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
        server = data["mcpServers"]["agentic-context"]
        if server["args"][-1] != "mcp-serve":
            raise AssertionError("registration must launch mcp-serve")

    def test_merges_preserving_other_servers(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"other-tool": {"command": "node",
                                          "args": ["server.js"]}}}),
            encoding="utf-8")
        if write_mcp_json(tmp_path) != "merged":
            raise AssertionError("existing .mcp.json must be merged")
        data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
        if "other-tool" not in data["mcpServers"]:
            raise AssertionError("merging must preserve other servers")
        if "agentic-context" not in data["mcpServers"]:
            raise AssertionError("merging must add the agentic-context server")


class TestIntegrate:
    def test_wires_all_three_surfaces(self, tmp_path):
        integrate(tmp_path)
        for name in ("CLAUDE.md", "AGENTS.md", ".mcp.json"):
            if not (tmp_path / name).exists():
                raise AssertionError("%s missing after integrate" % name)

    def test_integrate_is_idempotent(self, tmp_path):
        integrate(tmp_path)
        first = {n: (tmp_path / n).read_text(encoding="utf-8")
                 for n in ("CLAUDE.md", "AGENTS.md", ".mcp.json")}
        integrate(tmp_path)
        for name, before in first.items():
            after = (tmp_path / name).read_text(encoding="utf-8")
            if before != after:
                raise AssertionError("%s changed on a second integrate run" % name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
