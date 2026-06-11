"""
Serve Mode - persistent warm daemon
===================================
Loading the embedding model costs seconds on every CLI call; the daemon
loads the model and vector index ONCE and answers search/recall requests
in milliseconds over a localhost socket. The search CLI automatically
delegates to a running daemon and falls back to local execution.

Usage:
    python mcp.py serve                 Run the daemon (foreground)
    python mcp.py serve --background    Spawn the daemon detached
    python mcp.py serve --status        Ping the running daemon
    python mcp.py serve --stop          Stop the running daemon

Protocol: one JSON object per line over TCP on 127.0.0.1, authenticated
with a random token stored in .mcp/serve.json (written on start, removed
on clean shutdown).
"""

from pathlib import Path
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading

from .utils import Console, find_project_root


def serve_info_path(root: Path) -> Path:
    return Path(root) / ".mcp" / "serve.json"


def read_serve_info(root: Path):
    path = serve_info_path(root)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def request(root: Path, payload: dict, timeout: float = 15.0):
    """Send one request to a running daemon; None if absent or unreachable."""
    info = read_serve_info(root)
    if not info:
        return None
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])),
                                      timeout=timeout) as conn:
            body = dict(payload)
            body["token"] = info.get("token", "")
            conn.sendall(json.dumps(body).encode("utf-8") + b"\n")
            reader = conn.makefile("rb")
            line = reader.readline()
        if not line:
            return None
        return json.loads(line.decode("utf-8"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


class ServeAPI:
    """The operations the daemon answers, over a warm store and model."""

    def __init__(self, root: Path):
        self.root = Path(root)
        from .vector_store import VectorStore
        self.store = VectorStore()
        if self.store.load():
            Console.ok(f"Vector index warm: {len(self.store.chunks)} chunks")
        else:
            Console.warn("No vector index found; run 'mcp index-all' first")
        # Warm the embedding model so the first query is already fast.
        from .embeddings import embed_text
        embed_text("warmup")

    def handle(self, req: dict) -> dict:
        op = req.get("op")
        if op == "ping":
            return {"ok": True, "pid": os.getpid(),
                    "chunks": len(self.store.chunks)}
        if op == "search":
            results = self.store.search(str(req.get("query", "")),
                                        k=int(req.get("k", 10)))
            return {"ok": True, "results": [{
                "path": r.chunk.path,
                "line": r.chunk.line_start,
                "score": r.score,
                "name": r.chunk.name,
                "type": r.chunk.chunk_type,
            } for r in results]}
        if op == "recall":
            from . import memory as memory_mod
            mems = memory_mod.recall(str(req.get("query", "")),
                                     limit=int(req.get("k", 10)))
            return {"ok": True, "results": [{
                "key": m.key, "value": m.value, "project": m.project,
            } for m in mems]}
        if op == "stop":
            return {"ok": True, "stopping": True}
        return {"ok": False, "error": f"unknown op: {op}"}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline()
            req = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply({"ok": False, "error": "bad request"})
            return
        if req.get("token") != self.server.token:
            self._reply({"ok": False, "error": "bad token"})
            return
        try:
            resp = self.server.api.handle(req)
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        self._reply(resp)
        if resp.get("stopping"):
            self.server.stop_event.set()

    def _reply(self, obj: dict):
        try:
            self.wfile.write(json.dumps(obj).encode("utf-8") + b"\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server(root: Path):
    """Bind the daemon and write .mcp/serve.json; caller drives the loop."""
    api = ServeAPI(root)
    server = _Server(("127.0.0.1", 0), _Handler)
    server.api = api
    server.token = secrets.token_hex(16)
    server.stop_event = threading.Event()
    port = server.server_address[1]

    info_path = serve_info_path(root)
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps({
        "port": port, "token": server.token, "pid": os.getpid(),
    }), encoding="utf-8")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def run_server(root: Path) -> int:
    """Run the daemon until stopped (Ctrl-C or 'serve --stop')."""
    server, port = start_server(root)
    Console.ok(f"MCP daemon serving on 127.0.0.1:{port} (Ctrl-C or 'mcp serve --stop' to quit)")
    try:
        while not server.stop_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        try:
            serve_info_path(root).unlink()
        except OSError:
            pass
    Console.ok("Daemon stopped")
    return 0


def spawn_background(root: Path) -> int:
    """Spawn the daemon as a detached background process."""
    log_path = Path(root) / ".mcp" / "serve.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_py = Path(os.environ.get("MCP_ROOT", Path(__file__).resolve().parents[1])) / "mcp.py"
    creationflags = 0
    if os.name == "nt":
        creationflags = (subprocess.CREATE_NEW_PROCESS_GROUP
                         | getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    with open(log_path, "a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(mcp_py), "serve"],
            cwd=str(root), stdout=log, stderr=log,
            creationflags=creationflags)
    Console.ok(f"Daemon spawning in background (log: {log_path})")
    return 0


def main():
    """CLI entry point."""
    Console.header("MCP Serve")
    root = find_project_root() or Path.cwd()

    if "--status" in sys.argv:
        resp = request(root, {"op": "ping"}, timeout=5.0)
        if resp and resp.get("ok"):
            Console.ok(f"Daemon running (pid {resp.get('pid')}, "
                       f"{resp.get('chunks')} chunks warm)")
            return 0
        Console.warn("No daemon running")
        return 1

    if "--stop" in sys.argv:
        resp = request(root, {"op": "stop"}, timeout=5.0)
        if resp and resp.get("ok"):
            Console.ok("Daemon stopping")
            try:
                serve_info_path(root).unlink()
            except OSError:
                pass
            return 0
        Console.warn("No daemon running")
        return 1

    if "--background" in sys.argv:
        return spawn_background(root)

    return run_server(root)


if __name__ == "__main__":
    sys.exit(main())
