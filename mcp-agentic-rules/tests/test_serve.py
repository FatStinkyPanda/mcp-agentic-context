"""
Tests for the serve daemon.
===========================
In-process round-trip over the real TCP socket: ping, search, token
rejection, stop. Uses a tiny indexed project in tmp so no real .mcp is
touched.
"""

from pathlib import Path
import json
import os

import pytest

from scripts import serve as serve_mod
from scripts.vector_store import VectorStore


@pytest.fixture
def warm_project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".mcp").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "auth.ts").write_text(
        "export function authenticateUser(token: string): boolean {\n"
        "  return token.length > 0;\n}\n")
    old = os.getcwd()
    os.chdir(root)
    try:
        store = VectorStore()
        store.index_codebase(root)
        yield root
    finally:
        os.chdir(old)


@pytest.fixture
def running_server(warm_project):
    server, port = serve_mod.start_server(warm_project)
    try:
        yield warm_project, server, port
    finally:
        server.shutdown()
        try:
            serve_mod.serve_info_path(warm_project).unlink()
        except OSError:
            pass


class TestServe:
    def test_ping(self, running_server):
        root, _, _ = running_server
        resp = serve_mod.request(root, {"op": "ping"}, timeout=10.0)
        if not resp or not resp.get("ok"):
            raise AssertionError("ping failed: %r" % resp)
        if resp.get("chunks", 0) < 1:
            raise AssertionError("daemon must hold the warm index")

    def test_search_round_trip(self, running_server):
        root, _, _ = running_server
        resp = serve_mod.request(
            root, {"op": "search", "query": "authenticate user token", "k": 5},
            timeout=30.0)
        if not resp or not resp.get("ok"):
            raise AssertionError("search failed: %r" % resp)
        paths = [r["path"] for r in resp.get("results", [])]
        if not any("auth.ts" in p for p in paths):
            raise AssertionError("daemon search missed the indexed file: %r" % paths)

    def test_bad_token_rejected(self, running_server):
        root, _, port = running_server
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
            conn.sendall(json.dumps({"op": "ping", "token": "wrong"}).encode() + b"\n")
            line = conn.makefile("rb").readline()
        resp = json.loads(line.decode())
        if resp.get("ok"):
            raise AssertionError("requests with a bad token must be rejected")

    def test_stop_op_sets_event(self, running_server):
        root, server, _ = running_server
        resp = serve_mod.request(root, {"op": "stop"}, timeout=10.0)
        if not resp or not resp.get("ok"):
            raise AssertionError("stop failed: %r" % resp)
        if not server.stop_event.wait(5.0):
            raise AssertionError("stop op must set the shutdown event")

    def test_request_without_daemon_returns_none(self, tmp_path):
        if serve_mod.request(tmp_path, {"op": "ping"}) is not None:
            raise AssertionError("no serve.json must mean no daemon (None)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
