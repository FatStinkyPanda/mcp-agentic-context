"""
Agent Integration
=================
Makes an installed mcp-agentic-context discoverable to AI agents with zero
manual wiring:

- Appends a marker-delimited section to the project's CLAUDE.md (read
  automatically by Claude Code)
- Appends the same section to AGENTS.md (the cross-agent standard read by
  Cursor, Codex, and others)
- Generates or merges .mcp.json so MCP clients load the native server

Idempotent: re-running replaces the marked section in place and never
clobbers surrounding content or other configured MCP servers.

Usage:
    python mcp.py integrate
"""

from pathlib import Path
import json
import sys

from .utils import Console, find_project_root

MARK_START = "<!-- mcp-agentic-context:start -->"
MARK_END = "<!-- mcp-agentic-context:end -->"

SECTION = MARK_START + """
## MCP Agentic Context (AI agent tooling installed in this project)

This project has semantic code search, persistent agent memory, and shared
project state. Run commands as `python mcp-agentic-rules/mcp.py <command>`
(exit codes: 0 success, 1 failure), or use the native MCP tools (server
`agentic-context` in .mcp.json) when your client supports MCP.

WHEN to reach for these tools:
- BEFORE reading files to locate code by purpose: `search "what it does"`
  (a few hundred tokens) instead of opening files to look (thousands).
- INSTEAD OF reading a whole module for its shape: `skeleton <path>`
  (signatures only, no bodies).
- AT SESSION START: `state` (shared goal/tasks/notes) and `recall "topic"`
  (memory that survives context compaction and restarts).
- IMMEDIATELY when you learn something worth keeping:
  `remember "key" "value"`.
- WHEN unsure what a change affects: `impact <file>` (Python and TS/JS,
  pnpm-workspace aware).
- ONCE per repo (then incremental and cheap): `index-all`. For instant
  searches start the warm daemon: `serve --background`. Search results
  auto-refresh after file edits.
- BEFORE committing: `review .` and `security .` (on JS/TS projects these
  run the repo's own eslint/tsc/pnpm-audit).
""" + MARK_END + "\n"


def upsert_section(path: Path) -> str:
    """Create the file with the section, replace an existing marked section,
    or append. Returns 'created', 'updated', or 'appended'."""
    path = Path(path)
    if not path.exists():
        path.write_text(SECTION, encoding="utf-8")
        return "created"

    text = path.read_text(encoding="utf-8")
    if MARK_START in text and MARK_END in text:
        start = text.index(MARK_START)
        end = text.index(MARK_END) + len(MARK_END)
        # Swallow one trailing newline so updates do not accumulate blanks.
        if end < len(text) and text[end] == "\n":
            end += 1
        new_text = text[:start] + SECTION + text[end:]
        path.write_text(new_text, encoding="utf-8")
        return "updated"

    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + separator + SECTION, encoding="utf-8")
    return "appended"


def write_mcp_json(root: Path) -> str:
    """Generate or merge .mcp.json with the agentic-context server entry.
    Existing servers are preserved. Returns 'created' or 'merged'."""
    path = Path(root) / ".mcp.json"
    data = {}
    existed = path.exists()
    if existed:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            Console.warn(".mcp.json was unreadable; rebuilding it")
            data = {}

    servers = data.setdefault("mcpServers", {})
    servers["agentic-context"] = {
        "command": "python",
        "args": ["mcp-agentic-rules/mcp.py", "mcp-serve"],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "merged" if existed else "created"


def integrate(root: Path) -> int:
    """Wire up all three discovery surfaces for the given project root."""
    root = Path(root)
    for name in ("CLAUDE.md", "AGENTS.md"):
        action = upsert_section(root / name)
        Console.ok(f"{name}: {action}")
    action = write_mcp_json(root)
    Console.ok(f".mcp.json: {action}")
    return 0


def main():
    """CLI entry point."""
    Console.header("Agent Integration")
    root = find_project_root() or Path.cwd()
    Console.info(f"Project: {root}")
    return integrate(root)


if __name__ == "__main__":
    sys.exit(main())
