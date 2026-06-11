<!-- mcp-agentic-context:start -->
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
<!-- mcp-agentic-context:end -->
