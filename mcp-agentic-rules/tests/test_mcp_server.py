"""
Tests for the Model Context Protocol server.
============================================
In-process protocol tests (handshake, tools/list, tools/call, errors) plus
one real subprocess handshake over stdio to prove stdout discipline.
"""

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

from scripts.mcp_server import MCPServer, TOOLS

MCP_PY = Path(__file__).resolve().parent.parent / "mcp.py"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / ".mcp").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "thing.ts").write_text(
        "export function makeThing(n: number): string { return 't' + n; }\n")
    yield root


class TestProtocol:
    def test_initialize(self, project):
        server = MCPServer(project)
        resp = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        result = resp.get("result", {})
        if "protocolVersion" not in result or "serverInfo" not in result:
            raise AssertionError("initialize response malformed: %r" % resp)

    def test_tools_list(self, project):
        server = MCPServer(project)
        resp = server.handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        for expected in ("semantic_search", "recall_memory", "remember",
                         "autocontext", "skeleton", "project_state"):
            if expected not in names:
                raise AssertionError("tool %s missing from tools/list" % expected)
        if len(tools) != len(TOOLS):
            raise AssertionError("tools/list must reflect the TOOLS registry")

    def test_skeleton_tool_call(self, project):
        server = MCPServer(project)
        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "skeleton", "arguments": {"path": "src"}}})
        result = resp["result"]
        if result.get("isError"):
            raise AssertionError("skeleton tool errored: %r" % result)
        text = result["content"][0]["text"]
        if "makeThing" not in text:
            raise AssertionError("skeleton tool output missing signature: %s" % text)

    def test_project_state_tool_round_trip(self, project):
        server = MCPServer(project)
        server.handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "project_state",
                       "arguments": {"set_goal": "Ship it"}}})
        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "project_state", "arguments": {}}})
        text = resp["result"]["content"][0]["text"]
        if "Ship it" not in text:
            raise AssertionError("project_state did not persist the goal")

    def test_unknown_method_returns_error(self, project):
        server = MCPServer(project)
        resp = server.handle_message(
            {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"})
        if "error" not in resp or resp["error"]["code"] != -32601:
            raise AssertionError("unknown method must return -32601")

    def test_notification_gets_no_response(self, project):
        server = MCPServer(project)
        resp = server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"})
        if resp is not None:
            raise AssertionError("notifications must not produce responses")

    def test_unknown_tool_reports_error_content(self, project):
        server = MCPServer(project)
        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}}})
        if not resp["result"].get("isError"):
            raise AssertionError("unknown tool must produce isError content")


class TestStdioSubprocess:
    def test_handshake_over_real_stdio(self, project):
        env = dict(os.environ)
        env.pop("MCP_COMMAND", None)
        proc = subprocess.Popen(
            [sys.executable, str(MCP_PY), "mcp-serve"],
            cwd=str(project), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env)
        try:
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
            stdin_payload = "".join(json.dumps(m) + "\n" for m in messages)
            out, err = proc.communicate(stdin_payload, timeout=120)
            lines = [json.loads(l) for l in out.splitlines() if l.strip()]
            if len(lines) != 2:
                raise AssertionError(
                    "expected exactly 2 responses on stdout (no noise), got: %r" % out)
            if lines[0]["id"] != 1 or "protocolVersion" not in lines[0]["result"]:
                raise AssertionError("initialize over stdio malformed: %r" % lines[0])
            if lines[1]["id"] != 2 or not lines[1]["result"]["tools"]:
                raise AssertionError("tools/list over stdio malformed: %r" % lines[1])
        finally:
            proc.kill()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
