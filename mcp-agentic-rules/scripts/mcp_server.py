"""
Model Context Protocol Server
=============================
Exposes the toolkit's capabilities as REAL MCP tools over stdio JSON-RPC,
so MCP clients (Claude Code, Cursor, etc.) call semantic_search, recall,
remember, autocontext, skeleton, project_state, impact, review, security,
and todos natively - no shelling out, no output parsing, and the embedding
model stays warm for the life of the session. Stdlib only;
newline-delimited JSON-RPC 2.0.

Usage:
    python mcp.py mcp-serve

Client registration example (.mcp.json):
    {"mcpServers": {"agentic-context": {
        "command": "python",
        "args": ["mcp-agentic-rules/mcp.py", "mcp-serve"]}}}
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import contextlib
import json
import sys

from .utils import find_project_root

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcp-agentic-context", "version": "2.0.0"}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "semantic_search",
        "description": "Use this BEFORE reading files whenever you need to "
                       "locate code by purpose or meaning ('where is auth "
                       "handled', 'function that formats prices'). Costs a "
                       "few hundred tokens versus thousands for reading "
                       "files. Returns the most relevant functions/classes "
                       "with file paths and line numbers; results are "
                       "auto-refreshed after file edits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to find, by meaning"},
                "k": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Use this AT SESSION START and before re-deriving any "
                       "decision: persistent agent memory survives context "
                       "compaction and session restarts. Searches the current "
                       "project's memories plus globals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "all_projects": {"type": "boolean",
                                 "description": "Search every project's memories"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": "Use this IMMEDIATELY when you learn something worth "
                       "keeping (API quirks, conventions, decisions, gotchas) "
                       "- do not wait until the end of the session. Stored "
                       "memories outlive context compaction and restarts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
                "global_scope": {"type": "boolean",
                                 "description": "Visible from every project"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "autocontext",
        "description": "Use this ONCE at the start of a task to orient: loads "
                       "a layered project picture (map, memories, active "
                       "files, semantic matches) hard-capped to the budget. "
                       "Prefer semantic_search for follow-up lookups instead "
                       "of calling this repeatedly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Current task, guides selection"},
                "budget": {"type": "integer", "description": "Token budget (default 8000)"},
            },
        },
    },
    {
        "name": "skeleton",
        "description": "Use this INSTEAD OF reading a whole file or directory "
                       "when you only need its shape: returns signatures, "
                       "classes, and imports without bodies, at a fraction of "
                       "the tokens (TypeScript/JavaScript/Python and more).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory, relative to project root"},
                "budget_chars": {"type": "integer", "description": "Output cap (default 20000)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "project_state",
        "description": "Use this at session start to see the shared goal/"
                       "tasks/notes, and whenever you finish or plan an "
                       "increment (add_task/done/note). State is shared "
                       "across every agent session on this project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "set_goal": {"type": "string"},
                "add_task": {"type": "string"},
                "done": {"type": "integer", "description": "1-based task number to mark complete"},
                "note": {"type": "string"},
            },
        },
    },
    {
        "name": "impact",
        "description": "Use this BEFORE modifying or refactoring a shared "
                       "file: returns what imports it, transitively, and "
                       "which tests are affected (Python and TS/JS, pnpm "
                       "workspace aware).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string",
                         "description": "File path, relative to project root"},
            },
            "required": ["file"],
        },
    },
    {
        "name": "review",
        "description": "Use this BEFORE committing: automated code review of "
                       "the project or a path. On JS/TS projects it runs the "
                       "repo's OWN eslint and tsc and merges their findings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "File or directory, relative to project root (default: whole project)"},
                "strict": {"type": "boolean"},
            },
        },
    },
    {
        "name": "security",
        "description": "Use this BEFORE pushing: security audit for secrets, "
                       "injection risks, and (on pnpm projects) dependency "
                       "vulnerabilities via pnpm audit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "File or directory, relative to project root (default: whole project)"},
                "strict": {"type": "boolean"},
            },
        },
    },
    {
        "name": "todos",
        "description": "Use this when planning work or before declaring done: "
                       "lists TODO/FIXME/HACK comments across the codebase, "
                       "highest priority first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer",
                          "description": "Max items to return (default 30)"},
            },
        },
    },
]

# Tool output is conversation context; cap pathological reports.
MAX_TOOL_OUTPUT = 20000


def _cap(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    """Cap tool output so a pathological report cannot flood agent context."""
    if len(text) <= limit:
        return text
    return (text[:limit]
            + "\n\n[TRUNCATED] Output exceeded %d chars; narrow the path "
              "to see the rest." % limit)


class MCPServer:
    """Newline-delimited JSON-RPC 2.0 server for the MCP protocol."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._store = None  # lazy: model load only when search is first used

    # ---- tool implementations -------------------------------------------

    def _vector_store(self):
        if self._store is None:
            from .vector_store import VectorStore
            self._store = VectorStore()
            self._store.load()
        return self._store

    def tool_semantic_search(self, args: dict) -> str:
        store = self._vector_store()
        # Auto-fresh: reconcile the index before answering so edits made
        # moments ago are searchable. No-op when nothing changed.
        try:
            store.refresh(self.root)
        except Exception:
            pass
        if not store.chunks:
            return "No vector index found. Run 'python mcp.py index-all' first."
        results = store.search(str(args.get("query", "")), k=int(args.get("k", 10)))
        if not results:
            return "No matches."
        lines = []
        for r in results:
            lines.append(f"{r.chunk.path}:{r.chunk.line_start} "
                         f"({r.chunk.chunk_type} {r.chunk.name}, score {r.score:.3f})")
        return "\n".join(lines)

    def tool_recall_memory(self, args: dict) -> str:
        from . import memory as memory_mod
        mems = memory_mod.recall(str(args.get("query", "")),
                                 all_projects=bool(args.get("all_projects")))
        if not mems:
            return "No matching memories."
        return "\n".join(f"[{m.key}] ({m.project or 'global'}) {m.value}" for m in mems)

    def tool_remember(self, args: dict) -> str:
        from . import memory as memory_mod
        project = "" if args.get("global_scope") else None
        mem = memory_mod.remember(str(args.get("key", "")),
                                  str(args.get("value", "")), project=project)
        return f"Remembered [{mem.key}] in scope '{mem.project or 'global'}'."

    def tool_autocontext(self, args: dict) -> str:
        from .autocontext import get_auto_context
        return get_auto_context(task=str(args.get("task", "")),
                                token_budget=int(args.get("budget", 8000)),
                                root=self.root)

    def tool_skeleton(self, args: dict) -> str:
        from .skeleton import skeleton
        target = self.root / str(args.get("path", "."))
        if not target.exists():
            return f"Path not found: {target}"
        return skeleton(target, int(args.get("budget_chars", 20000)))

    def tool_project_state(self, args: dict) -> str:
        from .project_state import load_state, save_state, render
        state = load_state(self.root)
        changed = False
        if args.get("set_goal") is not None:
            state["goal"] = str(args["set_goal"])
            changed = True
        if args.get("add_task") is not None:
            from datetime import datetime
            state["tasks"].append({"text": str(args["add_task"]), "done": False,
                                   "created": datetime.utcnow().isoformat() + "Z"})
            changed = True
        if args.get("done") is not None:
            idx = int(args["done"]) - 1
            if 0 <= idx < len(state["tasks"]):
                state["tasks"][idx]["done"] = True
                changed = True
            else:
                return f"No such task: {args['done']}"
        if args.get("note") is not None:
            state["notes"].append(str(args["note"]))
            changed = True
        if changed:
            save_state(state, self.root)
        return render(state)

    def tool_impact(self, args: dict) -> str:
        from .impact import analyze_impact
        target = self.root / str(args.get("file", ""))
        if not target.exists():
            return f"File not found: {target}"
        report = analyze_impact(target, self.root)
        return _cap(report.to_markdown())

    def tool_review(self, args: dict) -> str:
        from .review import review_project, format_report_markdown
        path = self.root / str(args.get("path") or "")
        if not path.exists():
            return f"Path not found: {path}"
        report = review_project(path, strict=bool(args.get("strict")))
        return _cap(format_report_markdown(report))

    def tool_security(self, args: dict) -> str:
        from .security import security_audit
        path = self.root / str(args.get("path") or "")
        if not path.exists():
            return f"Path not found: {path}"
        report = security_audit(path, strict=bool(args.get("strict")))
        return _cap(report.to_markdown())

    def tool_todos(self, args: dict) -> str:
        from .todo_index import scan_project, group_by_priority
        excludes = ["node_modules", ".git", "dist", "build", ".next",
                    ".turbo", ".venv", "vendor", "__pycache__", ".mcp"]
        todos = scan_project(self.root, exclude_patterns=excludes)
        if not todos:
            return "No TODO/FIXME items found."
        limit = int(args.get("limit", 30))
        lines = []
        by_priority = group_by_priority(todos)
        for priority in sorted(by_priority):
            for item in by_priority[priority]:
                lines.append(f"[P{item.priority}] {item.type} "
                             f"{item.file}:{item.line} - {item.message}")
                if len(lines) >= limit:
                    break
            if len(lines) >= limit:
                break
        if len(todos) > limit:
            lines.append(f"... and {len(todos) - limit} more "
                         f"(raise limit to see them)")
        return _cap("\n".join(lines))

    # ---- protocol --------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> str:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        return handler(arguments or {})

    def handle_message(self, msg: dict) -> Optional[dict]:
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = msg_id is None

        def result(payload):
            return None if is_notification else {
                "jsonrpc": "2.0", "id": msg_id, "result": payload}

        def error(code, text):
            return None if is_notification else {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": text}}

        if method == "initialize":
            return result({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return result({})
        if method == "tools/list":
            return result({"tools": TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            try:
                # Tool modules print progress via Console to stdout; the
                # protocol owns stdout, so route everything they print to
                # stderr or the JSON-RPC stream gets corrupted.
                with contextlib.redirect_stdout(sys.stderr):
                    text = self.call_tool(params.get("name", ""),
                                          params.get("arguments") or {})
                return result({"content": [{"type": "text", "text": text}],
                               "isError": False})
            except Exception as e:
                return result({"content": [{"type": "text",
                                            "text": f"Tool failed: {e}"}],
                               "isError": True})
        return error(-32601, f"method not found: {method}")


def main():
    """Run the MCP server over stdio until stdin closes."""
    root = find_project_root() or Path.cwd()
    server = MCPServer(root)
    # Protocol messages own stdout; everything human goes to stderr.
    print(f"[mcp-serve] project root: {root}", file=sys.stderr, flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = server.handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
