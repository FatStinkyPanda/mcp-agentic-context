# MCP Agentic Context - AI Agent Instructions

## Available Commands (66 total)

Run with: `python mcp-agentic-rules/mcp.py <command>` (use `python`, not
`python3` - on Windows python3 is often a broken Store stub). Exit codes:
0 = success, 1 = failure.

### Session Start
```bash
mcp serve --background       # Warm daemon: instant search/recall afterwards
mcp autocontext --budget 8000  # Load relevant context, budget-capped
mcp state                    # Project goal, tasks, notes
mcp recall "topic"           # Search memory (this project + globals)
```

### Before Coding
```bash
mcp search "query"           # Semantic code search (all languages)
mcp skeleton src/            # Signature-only view of a module or tree
mcp impact file.ts           # What breaks? (pnpm-workspace aware)
```

### While Coding
```bash
mcp predict-bugs file.py     # Check for bugs
mcp context "query"          # Get targeted context
mcp state --add-task "..."   # Track increments (--done N to finish)
```

### After Coding
```bash
mcp review .                 # Code review (runs repo eslint/tsc on JS/TS)
mcp security .               # Security check (includes pnpm audit)
mcp test-gen file.py --impl  # Generate tests
mcp index-all                # Refresh indexes (incremental)
```

### Remember & Learn
```bash
mcp remember "key" "value"            # Store knowledge (this project)
mcp remember "key" "value" --global   # Visible from every project
mcp recall "query" [--all-projects]   # Search knowledge
mcp learn --patterns                  # View learned patterns
```

### MCP Clients (Claude Code, Cursor)
Register the native Model Context Protocol server instead of shelling out:
```json
{"mcpServers": {"agentic-context": {
    "command": "python",
    "args": ["mcp-agentic-rules/mcp.py", "mcp-serve"]}}}
```

## Hooks (via `mcp setup --hooks`)

- **pre-commit**: Auto-fix, risk check, security scan, review
- **post-commit**: Learning, index update
- **post-checkout**: Warm indexes

## Key Directories

- `mcp-agentic-rules/` - MCP package
- `.mcp/` - Index data, project state, daemon endpoint (auto-generated)

## Quick Reference

| Need | Command |
|------|---------|
| Context | `mcp autocontext [--budget N]` |
| Search | `mcp search "query"` |
| Shape of a module | `mcp skeleton <path>` |
| Goal/tasks | `mcp state` |
| Review | `mcp review .` |
| Bugs | `mcp predict-bugs .` |
| Impact | `mcp impact <file>` |
| Tests | `mcp test-gen file.py` |
| Memory | `mcp remember` / `mcp recall` |
| Speed | `mcp serve --background` |
